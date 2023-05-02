from kucoin.exceptions import KucoinAPIException
from kucoin.client import Client
from datetime import datetime
from loguru import logger
from math import floor
from json import dumps
from time import time
import sys

from config import (
    project_root,
    MIN_PRICE,
    list_time,
    COIN,
    COEFFICIENT,
)

from asyncio import (
    sleep as async_sleep,
    AbstractEventLoop,
    coroutine,
    run,
)


class Result:
    def __init__(self, order_id: str, balance: int, price: float) -> None:
        self.balance = balance
        self.order_id = order_id
        self.price = price


class CoinSeller:
    def __init__(self, account_name: str, api_key: str, api_secret: str, api_passphrase: str, proxy: str) -> None:
        self.account_name = account_name
        self.Client = Client(
            api_key=api_key,
            api_secret=api_secret,
            passphrase=api_passphrase,
        )
        self.Client.session.proxies.update({'https': proxy, 'http': proxy})
        self.balance_before_selling = None
        self.balance_after_selling = None

    async def start(self) -> None:
        logger.info('Waiting for listing...')
        last_time = 0
        while True:
            now = floor(time())
            if list_time > now and last_time != now:
                logger.info(f'Time before sending requests: {round(list_time - now)} seconds')
            last_time = now
            if list_time < now:
                await self.check_balance()
                break

    async def check_balance(self) -> None:
        response = self.Client.get_accounts(currency=COIN, account_type='trade')
        if not response:
            logger.info(f'There is no {COIN} tokens on your balance')
            sys.exit()

        balance = floor(float(response[0]['balance']))
        if balance:
            self.balance_before_selling = float(balance)
            logger.info(f'{self.account_name} | {COIN} balance: {balance}')
            await self.check_price_and_qty(balance)

    async def check_price_and_qty(self, balance: float) -> None:
        no_orders = True
        while no_orders:
            response = self.Client.get_ticker(symbol=f'{COIN}-USDT')
            if response is None:
                logger.info('It seems that there is no orders yet..')
                await async_sleep(0.5)
                continue

            price = (round(float(response['bestBid']) * COEFFICIENT, 3))
            if MIN_PRICE > price:
                logger.info('Not the right price for you..')
                await async_sleep(0.5)
                continue

            no_orders = False
            await self.sell_tokens(price, balance)

    async def sell_tokens(self, price: float, balance: float) -> None:
        n_digits = 2
        factor = 10 ** n_digits
        try:
            qty = floor(float(balance) * factor) / factor
            response = self.Client.create_limit_order(
                symbol=f'{COIN}-USDT',
                side='sell',
                price=str(price),
                size=str(qty))

            order_id = response['orderId']
            logger.info(f'An order for {qty} coins at price of {price} placed')
            await self.check_balance_after_selling(order_id, price)

        except KucoinAPIException as ex:
            logger.error(ex)
            await self.check_price_and_qty(balance)

    async def check_balance_after_selling(self, order_id: str, price: float) -> None:
        response = self.Client.get_accounts(currency=COIN, account_type='trade')
        balance = floor(float(response[0]['balance']))
        if balance <= 5:
            self.balance_after_selling = float(balance)
            logger.info(f'Completed. | {self.account_name}')
            result = Result(order_id, balance, price)
            self.process_results([result])

        elif balance > 5:
            await self.cancel_order(order_id, balance, price)

    async def cancel_order(self, order_id: str, balance: int, price: float):
        try:
            response = self.Client.cancel_order(order_id=order_id)
            logger.info(f'Order deleted | {self.account_name}')
            await self.check_price_and_qty(balance)
        except KucoinAPIException:
            logger.success(f'Completed. | {self.account_name}')
            result = Result(order_id, balance, price)
            self.process_results([result])

    def process_results(self, results: list[Result]) -> None:
        requests_data = []
        for result in results:
            try:
                requests_data.append({
                    'Account name': self.account_name,
                    'Price': result.price,
                    'Balance before selling': self.balance_before_selling,
                    'Balance after selling': float(result.balance),
                    'Order id': result.order_id,
                    'Result': f'You sold {self.balance_before_selling - self.balance_after_selling} tokens',
                })
            except AttributeError:
                continue

        data = {
            'requests_data': requests_data,
        }
        json_text = dumps(data, indent=4, ensure_ascii=False)
        self.write_to_file(json_text)

    def write_to_file(self, data: str) -> None:
        filename = self.account_name + '-' + datetime.now().strftime('%Y-%m-%d %H-%M-%S.json')
        directory = project_root / 'logs'
        path = directory / filename
        directory.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as file:
            file.write(data)

    def run(self) -> None:
        start_event_loop(self.start())


def start_event_loop(coroutine: coroutine) -> AbstractEventLoop:
    try:
        return run(coroutine)
    except RuntimeError as ex:
        logger.info(f'Something went wrong | {ex}')
