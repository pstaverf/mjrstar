import bundle_test_support
import asyncio
import hashlib
import hmac
import json
import time
import unittest
from unittest.mock import AsyncMock, patch

import payments_backend
from complete_games import CompleteGamesBackend
from games_backend import GameError
import test_games_backend as fixtures


class LaveshkaTests(unittest.IsolatedAsyncioTestCase):
    backend_type = CompleteGamesBackend
    asyncTearDown = fixtures.GamesBackendTests.asyncTearDown
    headers = fixtures.GamesBackendTests.headers

    async def asyncSetUp(self):
        await fixtures.GamesBackendTests.asyncSetUp(self)
        self.config_patch = patch.dict(payments_backend.__server_config__, LAVESHKA_API_KEY='LAVE-12-test', LAVESHKA_WEBHOOK_SECRET='whsec_test')
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.backend.lave_api = AsyncMock(side_effect=self.api)
        self.status = 'active'

    async def api(self, method, path, data=None):
        if path == '/buy/rate':
            return {'available':True, 'method':'phone', 'rate':'100', 'providers':[{'id':7,'name':'Phone','method':'phone','rate':'100','min_rub':'100','max_rub':'20000'}]}
        if path == '/invoices':
            return dict(data, id='inv_'+data['order_id'][3:],merchant_id=12,face_amount=data['amount'],status=self.status,pay_url='https://t.me/laveshka?startapp=test')
        if path.startswith('/invoices/'):
            order, body, obj = await self.backend.lave_load(self.order_id)
            return dict(obj,status=self.status)
        if path == '/buy/orders':
            return dict(data,id='buy_test',currency='USDT',status='awaiting_payment',amount_rub='220',rate='100',pay_phone='+996555123456',pay_country='KG',pay_operator='Test',pay_until='2099-01-01T00:00:00+00:00')
        raise AssertionError(path)

    async def create(self, provider='laveshka', rid='lave-request-00001', **extra):
        response = await self.client.post('/api/deposit/'+provider+'/create', headers=self.headers(request_id=rid),json=dict(amount=100,rid=rid,**extra))
        data = await response.json()
        if data.get('paymentId'):
            self.order_id=data['paymentId']
        return response,data

    async def webhook(self, obj, kind='invoice.paid', **changes):
        event=dict(id='evt_test',merchant_id=12,type=kind,data=obj)
        event.update(changes)
        body=json.dumps(event).encode()
        ts=str(int(time.time()))
        signature='v1='+hmac.new(b'whsec_test',ts.encode()+b'.'+body,hashlib.sha256).hexdigest()
        return await self.client.post('/laveshka',data=body,headers={'X-LavePay-Timestamp':ts,'X-LavePay-Signature':signature})

    async def test_invoice_webhook_replay_and_stats(self):
        response,data=await self.create()
        self.assertEqual(response.status,200)
        self.assertEqual(data['priceAmount'],'2.20')
        order,body,obj=await self.backend.lave_load(self.order_id)
        obj['status']='paid'
        for _ in range(2):
            response=await self.webhook(obj)
            self.assertEqual(response.status,200,await response.text())
        self.assertEqual(await self.runtime.get_balance(42),1100)
        response=await self.client.get('/api/profile/stats',headers=self.headers())
        self.assertEqual((await response.json())['deposits'],100)
        response=await self.client.get('/api/wallet/transactions?filter=deposit',headers=self.headers())
        self.assertTrue(any(row['description']=='Лавэшка' for row in (await response.json())['rows']))

    async def test_concurrent_delivery_once(self):
        await self.create()
        order,body,obj=await self.backend.lave_load(self.order_id)
        obj['status']='paid'
        await asyncio.gather(*(self.backend.lave_apply(self.order_id,obj,'evt_concurrent') for _ in range(5)))
        self.assertEqual(await self.runtime.get_balance(42),1100)

    async def test_pending_phone_and_late_completed(self):
        response,data=await self.create('sbp',method='phone',providerId=7)
        self.assertEqual(response.status,200, data)
        self.assertEqual(data['payPhone'],'+996555123456')
        self.assertEqual(await self.runtime.get_balance(42),1000)
        order,body,obj=await self.backend.lave_load(self.order_id)
        for status in ('cancelled','completed'):
            obj['status']=status
            response=await self.webhook(obj,'buy_order.'+status,id='evt_'+status)
            self.assertEqual(response.status,200,await response.text())
        self.assertEqual(await self.runtime.get_balance(42),1100)

    async def test_mismatched_money_merchant_key_rejected(self):
        await self.create()
        order,body,obj=await self.backend.lave_load(self.order_id)
        obj['status']='paid'
        for changes in ({'face_amount':'3.00'},{'merchant_id':13},{'order_id':'wrong'},{'currency':'GRAM'}):
            with self.assertRaises(GameError):
                await self.backend.lave_apply(self.order_id,dict(obj,**changes))
        self.assertEqual(await self.runtime.get_balance(42),1000)

    async def test_bad_signature_and_merchant(self):
        response=await self.client.post('/laveshka',json={})
        self.assertEqual(response.status,401)
        response=await self.webhook({},'webhook.test',merchant_id=13)
        self.assertEqual(response.status,401)
        response=await self.webhook({},'webhook.test')
        self.assertEqual(response.status,200)

    async def test_lost_response_saved_and_replayed_same_body(self):
        self.backend.lave_api=AsyncMock(side_effect=GameError('Timeout',502))
        response,data=await self.create()
        self.assertEqual(response.status,200)
        self.assertEqual(data['status'],'creating')
        sent=self.backend.lave_api.call_args.args
        self.backend.lave_api=AsyncMock(side_effect=self.api)
        await self.backend.lave_refresh(self.order_id)
        self.assertEqual(self.backend.lave_api.call_args.args,sent)
        response,again=await self.create()
        self.assertEqual(data['paymentId'],again['paymentId'])
        self.assertEqual(await self.runtime.get_balance(42),1000)

    async def test_cross_user_and_changed_payload(self):
        await self.create()
        response=await self.client.get('/api/deposit/laveshka/status?paymentId='+self.order_id,headers=self.headers(99))
        self.assertEqual(response.status,404)
        response=await self.client.post('/api/deposit/laveshka/create',headers=self.headers(request_id='lave-request-00001'),json={'amount':200,'rid':'lave-request-00001'})
        self.assertEqual(response.status,409)

    async def test_rollback_referral_failure(self):
        await self.create()
        order,body,obj=await self.backend.lave_load(self.order_id)
        obj['status']='paid'
        self.backend.referral_credit=AsyncMock(side_effect=RuntimeError('test'))
        with self.assertRaises(RuntimeError):
            await self.backend.lave_apply(self.order_id,obj)
        self.assertEqual(await self.runtime.get_balance(42),1000)
        order,_,_=await self.backend.lave_load(self.order_id)
        self.assertEqual(order['status'],'active')

    async def test_disabled_and_limits(self):
        with patch.dict(payments_backend.__server_config__,LAVESHKA_API_KEY=''):
            response,_=await self.create()
            self.assertEqual(response.status,503)
        response=await self.client.post('/api/deposit/laveshka/create',headers=self.headers(),json={'amount':1,'rid':'lave-request-00001'})
        self.assertEqual(response.status,400)
        response=await self.client.get('/api/deposit/laveshka/providers',headers=self.headers())
        self.assertEqual((await response.json())['providers'][0]['id'],7)

    async def test_url_validation(self):
        for url in ('javascript:alert(1)','https://evil.test/','https://t.me@evil.test/','http://t.me/laveshka'):
            self.assertFalse(self.backend.lave_safe_url(url,True))
        self.assertTrue(self.backend.lave_safe_url('https://qr.nspk.ru/test'))

    async def test_referral_reward_only_once(self):
        async with self.runtime._db_lock:
            await self.runtime.db().execute("INSERT INTO referrals(user_id,referrer_id,joined_at,is_premium,deposited) VALUES (42,99,'2026-01-01',0,0)")
            await self.runtime.db().commit()
        self.backend.wallet_runtime={'REF_DEPOSIT_PERCENT':0.10}
        await self.create()
        order,body,obj=await self.backend.lave_load(self.order_id)
        obj['status']='paid'
        await self.backend.lave_apply(self.order_id,obj)
        await self.backend.lave_apply(self.order_id,obj)
        async with self.runtime.db().execute("SELECT COUNT(*) FROM webapp_ref_events WHERE referral_id=42 AND kind='deposit'") as cursor:
            self.assertEqual((await cursor.fetchone())[0],1)

    async def test_stale_signature_and_raw_body_tamper(self):
        body=b'{"merchant_id":12,"id":"evt_test","type":"webhook.test"}'
        for ts,tamper in ((str(int(time.time())-301),False),(str(int(time.time())),True)):
            sig='v1='+hmac.new(b'whsec_test',ts.encode()+b'.'+body,hashlib.sha256).hexdigest()
            response=await self.client.post('/laveshka',data=body+b' ' if tamper else body,headers={'X-LavePay-Timestamp':ts,'X-LavePay-Signature':sig})
            self.assertEqual(response.status,401)

    async def test_polling_confirms_without_webhook(self):
        await self.create()
        self.status='paid'
        await self.backend.lave_refresh(self.order_id)
        self.assertEqual(await self.runtime.get_balance(42),1100)
        self.assertEqual(self.backend.lave_api.call_args.args[0],'GET')

    async def test_phone_wrong_provider_and_amount_rejected(self):
        await self.create('sbp',method='phone',providerId=7)
        order,body,obj=await self.backend.lave_load(self.order_id)
        for change in ({'provider_id':8},{'method':'sbp'},{'amount_usdt':'0.01'},{'idempotency_key':'wrong'}):
            with self.assertRaises(GameError):
                await self.backend.lave_apply(self.order_id,dict(obj,status='completed',**change))
        self.assertEqual(await self.runtime.get_balance(42),1000)


    async def test_event_id_deduplicated_across_orders(self):
        await self.create()
        _,_,obj=await self.backend.lave_load(self.order_id)
        await self.backend.lave_apply(self.order_id,dict(obj,status='paid'),'evt_once')
        await self.create(rid='lave-request-00002')
        _,_,obj=await self.backend.lave_load(self.order_id)
        await self.backend.lave_apply(self.order_id,dict(obj,status='paid'),'evt_once')
        self.assertEqual(await self.runtime.get_balance(42),1100)

    async def test_creation_error_visible_and_recovery_keeps_same_order(self):
        self.backend.lave_api=AsyncMock(side_effect=GameError('Лавэшка: API-ключ не принят.',502,'LAVE_API_ERROR'))
        response,data=await self.create()
        self.assertEqual(response.status,200)
        self.assertEqual(data['status'],'creating')
        self.assertIn('API-ключ не принят',data['creationError'])
        order_id=data['paymentId']
        response=await self.client.get('/api/deposit/laveshka/status?paymentId='+order_id,headers=self.headers())
        self.assertIn('API-ключ не принят',(await response.json())['creationError'])
        self.backend.lave_api=AsyncMock(side_effect=self.api)
        await self.backend.lave_refresh(order_id)
        result=await self.backend.lave_result(order_id,42)
        self.assertIsNone(result['creationError'])
        self.assertEqual(result['status'],'active')
        self.assertTrue(result['payUrl'])
        self.assertEqual(await self.runtime.get_balance(42),1000)

    async def test_missing_payment_link_is_not_silently_active(self):
        original=self.api
        async def no_link(method,path,data=None):
            obj=await original(method,path,data)
            obj['pay_url']=None
            return obj
        self.backend.lave_api=AsyncMock(side_effect=no_link)
        _,data=await self.create()
        self.assertEqual(data['status'],'creating')
        self.assertIn('pay_url',data['creationError'])

    async def test_api_rejection_redacted_but_actionable(self):
        from unittest.mock import MagicMock
        response=MagicMock()
        response.status=401
        response.json=AsyncMock(return_value={'ok':False,'error':{'code':'unauthorized','message':'PRIVATE_PROVIDER_MESSAGE'}})
        request_context=MagicMock()
        request_context.__aenter__=AsyncMock(return_value=response)
        request_context.__aexit__=AsyncMock(return_value=False)
        session=MagicMock()
        session.request.return_value=request_context
        session_context=MagicMock()
        session_context.__aenter__=AsyncMock(return_value=session)
        session_context.__aexit__=AsyncMock(return_value=False)
        with patch.object(payments_backend.aiohttp,'ClientSession',return_value=session_context):
            with self.assertRaises(GameError) as caught:
                await payments_backend.PaymentsMixin.lave_api(self.backend,'POST','/invoices',{'amount':'2.20'})
        self.assertIn('API-ключ не принят',str(caught.exception))
        self.assertIn('HTTP 401',str(caught.exception))
        self.assertNotIn('PRIVATE_PROVIDER_MESSAGE',str(caught.exception))
        self.assertNotIn('LAVE-12-test',str(caught.exception))
