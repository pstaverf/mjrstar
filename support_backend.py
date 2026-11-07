"""Persistent support tickets. Roles are derived only from the server's ADMIN_ID."""
import secrets
import time

from aiohttp import web
from games_backend import GameError, integer, serialize

CATEGORIES = {"general": "Общий вопрос", "payment": "Платежи", "game": "Игры", "account": "Аккаунт"}


class SupportMixin:
    def register_support(self, app):
        for path in ("state", "unread", "ticket", "file"):
            app.router.add_get("/api/support/" + path, self.handle_support)
        for path in ("ticket/create", "ticket/reply", "ticket/close", "message/edit", "message/delete", "file/delete", "typing", "faq/view", "upload"):
            app.router.add_post("/api/support/" + path, self.handle_support)

    async def initialize_support(self):
        self.support_typing = {}
        async with self.database_lock:
            db = self.database()
            for sql in (
                "CREATE TABLE IF NOT EXISTS webapp_support_tickets(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,subject TEXT NOT NULL,category TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,rev INTEGER NOT NULL DEFAULT 1,user_read INTEGER NOT NULL DEFAULT 0,admin_read INTEGER NOT NULL DEFAULT 0)",
                "CREATE INDEX IF NOT EXISTS idx_support_owner ON webapp_support_tickets(user_id,updated_at)",
                "CREATE TABLE IF NOT EXISTS webapp_support_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,ticket_id INTEGER NOT NULL,user_id INTEGER NOT NULL,author TEXT NOT NULL,text TEXT NOT NULL,created_at INTEGER NOT NULL,edited INTEGER NOT NULL DEFAULT 0,deleted INTEGER NOT NULL DEFAULT 0,rev INTEGER NOT NULL)",
                "CREATE INDEX IF NOT EXISTS idx_support_messages ON webapp_support_messages(ticket_id,id)",
                "CREATE INDEX IF NOT EXISTS idx_support_unread_v2 ON webapp_support_messages(ticket_id,author,deleted,id)",
                "CREATE TABLE IF NOT EXISTS webapp_support_files(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,ticket_id INTEGER,message_id INTEGER,mime TEXT NOT NULL,data BLOB NOT NULL,created_at INTEGER NOT NULL)",
                "CREATE INDEX IF NOT EXISTS idx_support_file_message ON webapp_support_files(message_id)",
                "CREATE TABLE IF NOT EXISTS webapp_support_audit(id INTEGER PRIMARY KEY AUTOINCREMENT,ticket_id INTEGER,user_id INTEGER NOT NULL,action TEXT NOT NULL,previous TEXT NOT NULL,created_at INTEGER NOT NULL)",
            ):
                await db.execute(sql)
            await db.execute("DELETE FROM webapp_support_files WHERE ticket_id IS NULL AND created_at < ?", (int(time.time()) - 86400,))
            await db.commit()

    def support_admin(self, user_id):
        configured = getattr(self, "wallet_runtime", {}).get("ADMIN_ID")
        return isinstance(configured, int) and not isinstance(configured, bool) and user_id == configured

    async def support_ticket(self, db, ticket_id, user):
        ticket_id = integer(ticket_id, 1, 2**53 - 1)
        async with db.execute("SELECT id,user_id,subject,category,status,created_at,updated_at,rev,user_read,admin_read FROM webapp_support_tickets WHERE id=?", (ticket_id,)) as cur:
            row = await cur.fetchone()
        if row is None or (row[1] != user.id and not self.support_admin(user.id)):
            raise GameError("Тикет не найден.", 404)
        return row

    async def support_ticket_json(self, db, row, admin=False):
        if len(row) >= 12:
            preview, unread = row[10], row[11]
        else:
            async with db.execute("SELECT text FROM webapp_support_messages WHERE ticket_id=? AND deleted=0 ORDER BY id DESC LIMIT 1", (row[0],)) as cur:
                latest = await cur.fetchone()
            preview = latest[0] if latest else ""
            author = "user" if admin else "staff"
            read = row[9] if admin else row[8]
            async with db.execute("SELECT COUNT(*) FROM webapp_support_messages WHERE ticket_id=? AND author=? AND deleted=0 AND id>?", (row[0], author, read)) as cur:
                unread = (await cur.fetchone())[0]
        return {"id": row[0], "num": str(row[0]), "userId": row[1], "subject": row[2], "category": row[3], "categoryLabel": CATEGORIES.get(row[3], row[3]), "status": row[4], "createdAt": row[5], "updatedAt": row[6], "preview": preview[:150], "unread": unread, "canReply": True}

    async def support_message_json(self, db, row, admin=False, file_map=None):
        if file_map is None:
            async with db.execute("SELECT id FROM webapp_support_files WHERE message_id=?", (row[0],)) as cur:
                files = [{"t": value[0]} for value in await cur.fetchall()]
        else:
            files = file_map.get(row[0], [])
        return {"id": row[0], "userId": row[2], "author": row[3], "name": "Поддержка" if row[3] == "staff" else "Игрок", "text": row[4] if not row[7] or admin else "", "createdAt": row[5], "edited": bool(row[6]), "deleted": bool(row[7]), "files": files if not row[7] else [], "rev": row[8]}

    async def support_counters(self, db, user):
        admin = self.support_admin(user.id)
        owner = "" if admin else "AND t.user_id=?"
        read_column = "admin_read" if admin else "user_read"
        args = ("user" if admin else "staff",) + (() if admin else (user.id, user.id))
        sql = f"""SELECT
            (SELECT COUNT(*) FROM webapp_support_tickets t JOIN webapp_support_messages m ON m.ticket_id=t.id
                WHERE m.author=? AND m.deleted=0 AND m.id>t.{read_column} {owner}),
            (SELECT COUNT(*) FROM webapp_support_tickets t WHERE t.status!='closed' {owner})"""
        async with db.execute(sql, args) as cur:
            return await cur.fetchone()

    async def support_snapshot(self, db, user):
        admin = self.support_admin(user.id)
        where, args = ("", ()) if admin else ("WHERE t.user_id=?", (user.id,))
        read_column = "admin_read" if admin else "user_read"
        author = "user" if admin else "staff"
        sql = f"""SELECT t.id,t.user_id,t.subject,t.category,t.status,t.created_at,t.updated_at,t.rev,t.user_read,t.admin_read,
            COALESCE((SELECT text FROM webapp_support_messages WHERE ticket_id=t.id AND deleted=0 ORDER BY id DESC LIMIT 1),''),
            (SELECT COUNT(*) FROM webapp_support_messages WHERE ticket_id=t.id AND author=? AND deleted=0 AND id>t.{read_column})
            FROM webapp_support_tickets t {where} ORDER BY t.updated_at DESC,t.id DESC LIMIT 200"""
        async with db.execute(sql, (author, *args)) as cur:
            rows = await cur.fetchall()
        tickets = [await self.support_ticket_json(db, row, admin) for row in rows]
        unread, open_count = await self.support_counters(db, user)
        return {"ok": True, "isAdmin": admin, "teamName": "Поддержка MajorStars", "online": False, "mode": "offline", "replyEta": "по мере обработки", "nextOpen": "после ответа администратора", "today": self.clock().weekday(), "schedule": [{"on": False, "from": "", "to": ""} for _ in range(7)], "categories": [{"key": k, "label": v} for k, v in CATEGORIES.items()], "limits": {"subjectMin": 3, "subjectMax": 120, "textMax": 4000, "maxImages": 4, "editWindow": 172800}, "tickets": tickets, "unread": unread, "openCount": open_count, "faq": [], "ban": None}

    async def support_files_attach(self, db, user_id, file_ids, ticket_id, message_id):
        if not isinstance(file_ids, list) or len(file_ids) > 4 or any(not isinstance(x, str) for x in file_ids) or len(set(file_ids)) != len(file_ids):
            raise GameError("Можно приложить до четырёх фотографий.")
        for file_id in file_ids:
            result = await db.execute("UPDATE webapp_support_files SET ticket_id=?,message_id=? WHERE id=? AND user_id=? AND ticket_id IS NULL", (ticket_id, message_id, file_id, user_id))
            if result.rowcount != 1:
                raise GameError("Фото не найдено или уже использовано.")

    async def handle_support(self, request):
        try:
            return await self.support_dispatch(request)
        except GameError as error:
            return self.failure(error)

    async def support_dispatch(self, request):
        user = self.validate_user(request)
        admin = self.support_admin(user.id)
        action = request.path.removeprefix("/api/support/")
        now = int(time.time())
        if action == "upload":
            if request.content_length and request.content_length > 2 * 1024 * 1024:
                raise GameError("Фото должно быть не больше 2 MB.", 413)
            body = bytearray()
            async for chunk in request.content.iter_chunked(65536):
                body.extend(chunk)
                if len(body) > 2 * 1024 * 1024:
                    raise GameError("Фото должно быть не больше 2 MB.", 413)
            mime = "image/png" if body.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg" if body.startswith(b"\xff\xd8\xff") else "image/webp" if body[:4] == b"RIFF" and body[8:12] == b"WEBP" else None
            if not mime:
                raise GameError("Подходят JPG, PNG и WebP.")
            async with self.database_lock:
                db = self.database()
                try:
                    await db.execute("BEGIN IMMEDIATE")
                    await db.execute("DELETE FROM webapp_support_files WHERE ticket_id IS NULL AND created_at<?", (now - 86400,))
                    async with db.execute("SELECT COUNT(*) FROM webapp_support_files WHERE user_id=? AND created_at>?", (user.id, now - 86400)) as cur:
                        if (await cur.fetchone())[0] >= 40:
                            raise GameError("Лимит фотографий за сутки исчерпан.", 429)
                    file_id = secrets.token_urlsafe(32)
                    await db.execute("INSERT INTO webapp_support_files(id,user_id,mime,data,created_at) VALUES (?,?,?,?,?)", (file_id, user.id, mime, bytes(body), now))
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise
            return self.response({"ok": True, "file": {"id": file_id}})
        if request.method == "GET":
            async with self.database_lock:
                db = self.database()
                if action == "state":
                    return self.response(await self.support_snapshot(db, user))
                if action == "unread":
                    unread, _ = await self.support_counters(db, user)
                    return self.response({"ok": True, "unread": unread})
                if action == "file":
                    async with db.execute("SELECT user_id,ticket_id,mime,data FROM webapp_support_files WHERE id=?", (request.query.get("t", ""),)) as cur:
                        row = await cur.fetchone()
                    if row is None:
                        raise GameError("Фото не найдено.", 404)
                    if row[1] is not None:
                        await self.support_ticket(db, row[1], user)
                    elif row[0] != user.id:
                        raise GameError("Фото не найдено.", 404)
                    return web.Response(body=row[3], content_type=row[2], headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
                ticket = await self.support_ticket(db, request.query.get("id", ""), user)
                after = integer(request.query.get("after", "0"), 0, 2**53 - 1)
                rev = integer(request.query.get("rev", "0"), 0, 2**53 - 1)
                async with db.execute("SELECT id,ticket_id,user_id,author,text,created_at,edited,deleted,rev FROM webapp_support_messages WHERE ticket_id=? AND (id>? OR rev>?) ORDER BY id LIMIT 500", (ticket[0], after, rev)) as cur:
                    rows = await cur.fetchall()
                file_map = {}
                if rows:
                    ids = [row[0] for row in rows]
                    async with db.execute("SELECT message_id,id FROM webapp_support_files WHERE message_id IN (" + ",".join("?" for _ in ids) + ")", ids) as cur:
                        for message_id, file_id in await cur.fetchall():
                            file_map.setdefault(message_id, []).append({"t": file_id})
                messages = [await self.support_message_json(db, row, admin, file_map) for row in rows]
                # Advance the reader only through delivered messages, never unseen rows.
                read_index = 9 if admin else 8
                delivered = max((r[0] for r in rows), default=0)
                if delivered > ticket[read_index]:
                    column = "admin_read" if admin else "user_read"
                    await db.execute(f"UPDATE webapp_support_tickets SET {column}=? WHERE id=?", (delivered, ticket[0]))
                    await db.commit()
                    ticket = list(ticket)
                    ticket[read_index] = delivered
                result = {"ok": True, "isAdmin": admin, "ticket": await self.support_ticket_json(db, ticket, admin), "messages": [m for m in messages if m["id"] > after], "changed": [m for m in messages if m["id"] <= after], "rev": ticket[7] if len(rows) < 500 else min(r[8] for r in rows), "teamName": "Поддержка MajorStars", "online": False, "ban": None, "typing": self.support_typing.get((ticket[0], not admin), 0) > time.monotonic()}
                return self.response(result)
        payload = await self.payload(request)
        self.validate_user(request, payload)
        if action == "faq/view":
            return self.response({"ok": True})
        if action == "typing":
            async with self.database_lock:
                ticket = await self.support_ticket(self.database(), payload.get("id"), user)
            # Bound transient typing entries and discard expired records.
            self.support_typing = {k: v for k, v in self.support_typing.items() if v > time.monotonic()}
            self.support_typing[(ticket[0], admin)] = time.monotonic() + 6
            return self.response({"ok": True})
        key, signature = self.request_identity(request, payload)
        async with self.database_lock:
            db = self.database()
            try:
                await db.execute("BEGIN IMMEDIATE")
                cached = await self.load_receipt(db, user.id, key, signature)
                if cached:
                    await db.commit()
                    return self.response(cached)
                if action == "file/delete":
                    if not isinstance(payload.get("id"), str):
                        raise GameError("Некорректный идентификатор фото.")
                    await db.execute("DELETE FROM webapp_support_files WHERE id=? AND user_id=? AND ticket_id IS NULL", (payload.get("id"), user.id))
                    result = {"ok": True}
                else:
                    text = payload.get("text", "")
                    if not isinstance(text, str) or len(text) > 4000:
                        raise GameError("Сообщение должно содержать до 4000 символов.")
                    text = text.strip()
                    files = payload.get("files", [])
                    if not isinstance(files, list) or len(files) > 4:
                        raise GameError("Можно приложить до четырёх фотографий.")
                    if action == "ticket/create":
                        subject = payload.get("subject")
                        category = payload.get("category", "general")
                        if not isinstance(subject, str) or not 3 <= len(subject.strip()) <= 120 or not isinstance(category, str) or category not in CATEGORIES or (len(text) < 5 and not files):
                            raise GameError("Проверьте тему, категорию и сообщение.")
                        async with db.execute("SELECT COUNT(*) FROM webapp_support_tickets WHERE user_id=? AND status!='closed'", (user.id,)) as cur:
                            if (await cur.fetchone())[0] >= 10:
                                raise GameError("Можно иметь не больше 10 открытых тикетов.", 429)
                        cur = await db.execute("INSERT INTO webapp_support_tickets(user_id,subject,category,created_at,updated_at) VALUES (?,?,?,?,?)", (user.id, subject.strip(), category, now, now))
                        ticket = await self.support_ticket(db, cur.lastrowid, user)
                    else:
                        ticket = await self.support_ticket(db, payload.get("id"), user)
                    tid, revision = ticket[0], ticket[7] + 1
                    result = {"ok": True}
                    if action in {"ticket/create", "ticket/reply"}:
                        if not text and not files:
                            raise GameError("Введите сообщение или приложите фото.")
                        author = "staff" if admin and ticket[1] != user.id else "user"
                        cur = await db.execute("INSERT INTO webapp_support_messages(ticket_id,user_id,author,text,created_at,rev) VALUES (?,?,?,?,?,?)", (tid, user.id, author, text, now, revision))
                        await self.support_files_attach(db, user.id, files, tid, cur.lastrowid)
                        await db.execute("UPDATE webapp_support_tickets SET status=? WHERE id=?", ("answered" if author == "staff" else "open", tid))
                        async with db.execute("SELECT id,ticket_id,user_id,author,text,created_at,edited,deleted,rev FROM webapp_support_messages WHERE id=?", (cur.lastrowid,)) as cur:
                            result["message"] = await self.support_message_json(db, await cur.fetchone(), admin)
                        result["messages"] = [result["message"]]
                    elif action == "ticket/close":
                        await db.execute("UPDATE webapp_support_tickets SET status='closed' WHERE id=?", (tid,))
                    elif action in {"message/edit", "message/delete"}:
                        mid = integer(payload.get("mid"), 1, 2**53 - 1)
                        async with db.execute("SELECT id,ticket_id,user_id,author,text,created_at,edited,deleted,rev FROM webapp_support_messages WHERE id=? AND ticket_id=?", (mid, tid)) as cur:
                            message = await cur.fetchone()
                        if message is None or message[2] != user.id or message[7] or ticket[4] == "closed" or now - message[5] > 172800:
                            raise GameError("Сообщение нельзя изменить.", 403)
                        await db.execute("INSERT INTO webapp_support_audit(ticket_id,user_id,action,previous,created_at) VALUES (?,?,?,?,?)", (tid, user.id, action, serialize(list(message)), now))
                        if action == "message/edit":
                            if not text:
                                raise GameError("Сообщение не может быть пустым.")
                            await db.execute("UPDATE webapp_support_messages SET text=?,edited=1,rev=? WHERE id=?", (text, revision, mid))
                        else:
                            await db.execute("UPDATE webapp_support_messages SET deleted=1,rev=? WHERE id=?", (revision, mid))
                        async with db.execute("SELECT id,ticket_id,user_id,author,text,created_at,edited,deleted,rev FROM webapp_support_messages WHERE id=?", (mid,)) as cur:
                            result["message"] = await self.support_message_json(db, await cur.fetchone(), admin)
                        result["changed"] = True
                    else:
                        raise GameError("Неизвестное действие.", 404)
                    await db.execute("UPDATE webapp_support_tickets SET rev=?,updated_at=? WHERE id=?", (revision, now, tid))
                    await db.execute("INSERT INTO webapp_support_audit(ticket_id,user_id,action,previous,created_at) VALUES (?,?,?,?,?)", (tid, user.id, action, "", now))
                    ticket = await self.support_ticket(db, tid, user)
                    result["ticket"] = await self.support_ticket_json(db, ticket, admin)
                await self.save_receipt(db, user.id, key, signature, result)
                await db.commit()
                return self.response(result)
            except BaseException:
                await db.rollback()
                raise
