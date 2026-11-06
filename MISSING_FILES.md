# MjrStar: временно отсутствующие компоненты

Из `kas.zip` распаковано 309 файлов. Отдельно из `origin/main` добавлены `support.js`, `support.css`, `sw.js`.

## Запуск

`python main.py` запускает существующего бота и раздачу WebApp на `0.0.0.0:16341`.
Прокси домена `https://mjrr.wisp.uno` должен направлять `/webhook`, `/app`, `/api/*` и пути ресурсов на этот порт.
Настройки секретов не изменены.

## Backend

Подключены реальные маршруты:

- `POST /api/auth/telegram` — проверка подписи Telegram initData и срока действия (24 часа, допустимое расхождение часов вперёд — 60 секунд).
- `GET /api/state` — текущий баланс и дата регистрации из той же таблицы `balances` в `bot.db`, которую использует бот; имя и аватар берутся из подписанных данных Telegram.
- `GET /api/referral` — реферальная ссылка, число приглашённых и заработок из существующих таблиц бота.

Перед всеми `/api` и `/api/*` в основном приложении работает `webapp_api_guard`: отсутствие или подделка Telegram initData, просроченная подпись и чужой `uid` в URL дают HTTP 404 без кеширования. Для `/api/auth/telegram` проверяются подписанные данные из тела запроса. Подстановка `X-Forwarded-For` не даёт доступ. Статика и Telegram webhook этим middleware не ограничиваются.

Ограничение по IP 78.154.103.13 не включено: запросы WebApp идут из браузеров игроков, а пользователь уточнил, что цель — защита от поддельных ставок. С действительной подписью своей сессии игрок технически может обращаться к API через curl; надёжно отличить такой запрос от браузера невозможно. Чужой аккаунт, сумму выплаты и результаты игр клиент задавать не может.

Клиент отправляет `X-Telegram-Init-Data` только в API-запросах на свой домен. Пользователь определяется по проверенной подписи; запрос чужого `uid` отклоняется.
Баланс не кешируется, клиент не может записать его произвольным запросом. Существующий опрос обновляет баланс каждые 20 секунд при видимой странице и при возвращении в приложение.

Подключены игровые обработчики в `games_backend.py`, `complete_games.py`, `game_rules.py`, `live_games.py`:

- Кено: таблицы, ставка, история, карточка раунда, настройка/запуск/остановка автоигры.
- Upgrade: ставка, история, карточка раунда, настройка/запуск/остановка автоигры; сохранены значения из интерфейса (house edge 6%, нижняя граница roll 0.0946).
- Мины и Лесенка: таблицы коэффициентов, начало, восстановление активного раунда, ход, получение выигрыша, история и карточка завершённого раунда; настройка/запуск/остановка автоигры и атомарный `/auto/round`.
- HiLo и RedBlack: начало, выбор карты, получение выигрыша, восстановление раунда, история и проверка сида; серверная версия состояния защищает от устаревших ходов.
- Blackjack: раздача, hit/stand/double/split, скрытая карта дилера, натуральный blackjack, возврат при равенстве, история и раскрытие колоды после завершения.
- Coinflip: серия, задержка броска, восстановление, получение выигрыша, история и коммит следующего раунда.
- Claw, Baccarat и Wheel: реальные атомарные ставки и выплаты, серверные коэффициенты, предварительные коммиты, история и карточки раундов.
- Escape Solo: уровни и формулы из клиента, предварительный коммит, исход и траектория, восстановление анимации, история.
- Crash и цветная Roulette: общие сохраняемые раунды, серверный цикл переходов, ставки, выплаты и история; Crash поддерживает ручной/автоматический вывод и очередь следующего раунда.
- `/api/pvp/commission`: комиссия 1%. Это пока только конфигурационный маршрут, не реализация PvP-расчётов.

Для остальных `/api/*` временный обработчик `webapp_api_unavailable` в `main.py` отвечает HTTP 503 с `ok: false`.
Полный игровой объём ещё не завершён: отсутствуют Telegram emoji-игры (кости, слоты, боулинг, дартс, баскетбол, футбол), все PvP-режимы, Portal, Race, Bomb, Sumo и страница DogHouse. В `/api/games/off` незавершённые игры помечены отключёнными. Платёжные и административные обработчики WebApp также не реализованы.

Проверки: 47 автоматических тестов SQLite/aiohttp, включая старые игры и новые финансовые операции, версии ходов, повторы запросов, откат при ошибке записи, предварительные коммиты, формулы раздач, восстановление и однократные выплаты Crash/Roulette. Дополнительно пройдены регрессии авторизации, общего баланса, HTTP-маршрутов и 14 реферальных сценариев. Полный запуск с Telegram webhook и браузерные end-to-end проверки ещё не выполнены.
Код интерфейса в `app.js` вызывает эти серверные маршруты, но не заменяет их.
Существующая функциональность Telegram-бота остаётся в `main.py`.
При добавлении остальных обработчиков их маршруты необходимо регистрировать перед временным маршрутом `/api/{path:.*}`.

## Скрипты и стили

Не добавлены `admin.js`, `gadmin.js`, `srv_panel.js`, `srv_panel.css`.
Они возвращают 404, а не фиктивный успешный ответ: реализацию этих панелей восстановить без исходников нельзя.

## Шрифты

Подключены исходные `Unbounded-Regular.ttf`, `Unbounded-Medium.ttf` и `Montserrat-SemiBold.ttf`.
Вместо отсутствующих Unbounded 600/800 временно используется Medium; вместо Involve и Montserrat Regular — Montserrat SemiBold.

## Изображения и анимации

Для отсутствующих медиафайлов в разрешённых каталогах сервер возвращает нейтральный ресурс из `placeholders/`.
Ответ помечается заголовком `X-MjrStar-Placeholder: 1` и не сохраняется в HTTP-кеш или кеш service worker.
После добавления настоящего файла по запрашиваемому пути он будет отдаваться вместо заглушки без изменения кода.

Ниже перечислены отсутствующие прямые ссылки. Список не включает все пути, собираемые динамически из частей строк.

Обнаружено отсутствующих прямых путей: 49.

- `images/legacy_icons/coin_toggle.png`
- `images/legacy_icons/dice_basketball.png`
- `images/legacy_icons/dice_bowling.png`
- `images/legacy_icons/dice_darts.png`
- `images/legacy_icons/dice_football.png`
- `images/legacy_icons/dice_kosti.png`
- `images/legacy_icons/dice_slots.png`
- `images/legacy_icons/fair_basketball.png`
- `images/legacy_icons/fair_bowling.png`
- `images/legacy_icons/fair_crash.png`
- `images/legacy_icons/fair_darts.png`
- `images/legacy_icons/fair_football.png`
- `images/legacy_icons/fair_kosti.png`
- `images/legacy_icons/fair_ladder.png`
- `images/legacy_icons/fair_mines.png`
- `images/legacy_icons/fair_pvp.png`
- `images/legacy_icons/fair_slots.png`
- `images/legacy_icons/fair_upgrade.png`
- `images/legacy_icons/popular_crash.png`
- `images/legacy_icons/popular_ladder.png`
- `images/legacy_icons/popular_mines.png`
- `images/legacy_icons/popular_upgrader.png`
- `images/race_logo.svg`
- `images/ruletka.png`
- `lottie/NavBar/StarsTerms.lottie`
- `lottie/NavBar/StarsTerms.png`
- `lottie/ThemeSupport.svg`
- `lottie/images/FireBonus.lottie`
- `lottie/images/ИсторияНачисленияРеф.lottie`
- `lottie/images/МоиИгрыРаздел.png`
- `lottie/БарабанБонусов/BonusWheel.lottie`
- `lottie/ИграBlackJack/TableBlackJack.jpg`
- `lottie/ИграBlackJack/krupie.png`
- `lottie/ИграRace/Кубок.lottie`
- `lottie/ИграМиныЛесенка/Бомба.lottie`
- `lottie/ИграМиныЛесенка/Бомба.png`
- `lottie/ИграОрелРешка/ОрелРешка.lottie`
- `lottie/СистемаЧеков/СистемаЧеков.png`
- `xrocket/bnb.png`
- `xrocket/btc.png`
- `xrocket/eth.png`
- `xrocket/gram.png`
- `xrocket/usdt.png`
- `ИграРулетка/СтрелкаВниз.png`
- `Капча/SlotsMachine.png`
- `Капча/Бар.png`
- `Капча/Виноград.png`
- `Капча/Лимон.png`
- `Капча/Семь.png`
