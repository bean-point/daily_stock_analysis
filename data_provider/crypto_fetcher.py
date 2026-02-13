# -*- coding: utf-8 -*-
"""
===================================
CryptoFetcher - 加密货币数据源
===================================

数据来源：Binance API（免费，无需 API Key）
特点：
- 支持 BTC、ETH 等主流加密货币
- 24小时交易，无休市时间
- 数据实时性高

支持的交易对格式：
- BTCUSDT、ETHUSDT（USDT计价）
- BTCUSD、ETHUSD（USD计价，自动转为USDT）

优先级：1（仅对加密货币代码有效，股票代码会跳过）
"""
import logging
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional

from .base import BaseFetcher, DataFetchError, STANDARD_COLUMNS
from .realtime_types import ChipDistribution

logger = logging.getLogger(__name__)


class CryptoFetcher(BaseFetcher):
    """
    加密货币数据源实现 - 使用 Binance API
    
    优先级：1（加密货币优先使用此数据源）
    数据来源：Binance Spot API
    """
    
    name = "CryptoFetcher"
    priority = 1
    
    # 主流加密货币代码映射
    CRYPTO_NAMES = {
        'BTC': '比特币',
        'ETH': '以太坊',
        'BNB': '币安币',
        'XRP': '瑞波币',
        'SOL': 'Solana',
        'DOGE': '狗狗币',
        'ADA': 'Cardano',
        'AVAX': 'Avalanche',
        'DOT': 'Polkadot',
        'LINK': 'Chainlink',
        'CFX': 'Conflux',
        'XMR': '门罗币',
    }
    
    def _is_crypto_code(self, code: str) -> bool:
        """
        判断是否为加密货币代码
        
        支持的格式：
        - BTCUSDT、ETHUSDT
        - BTC-USDT、ETH-USD
        - BTC、ETH（简写，默认转为 BTCUSDT）
        """
        code = code.upper().strip()
        
        # 包含 USDT 或 USD 后缀
        if 'USDT' in code or 'USD' in code:
            return True
        
        # 纯加密货币代码（如 BTC、ETH）
        base_code = code.replace('USDT', '').replace('USD', '')
        if base_code in self.CRYPTO_NAMES:
            return True
        
        return False
    
    def _convert_symbol(self, code: str) -> str:
        """
        转换为 Binance 标准格式
        
        Args:
            code: 原始代码，如 'BTCUSDT', 'BTC-USD', 'BTC'
            
        Returns:
            Binance 格式，如 'BTCUSDT'
        """
        code = code.upper().strip().replace('-', '').replace('_', '')
        
        # 纯代码如 BTC、ETH，默认转为 BTCUSDT
        if code in self.CRYPTO_NAMES:
            return f"{code}USDT"
        
        # USD 转为 USDT（Binance 主要用 USDT）
        if code.endswith('USD') and not code.endswith('USDT'):
            code = code.replace('USD', 'USDT')
        
        return code
    
    def get_stock_name(self, stock_code: str) -> str:
        """获取加密货币名称"""
        code = stock_code.upper().replace('USDT', '').replace('USD', '')
        return self.CRYPTO_NAMES.get(code, f"{code}加密货币")
    
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取加密货币 K 线数据
        
        优先使用 Binance API，失败时自动切换到 CoinGecko 备用
        
        Args:
            stock_code: 交易对代码，如 'BTCUSDT'
            start_date: 开始日期 'YYYY-MM-DD'
            end_date: 结束日期 'YYYY-MM-DD'
            
        Returns:
            DataFrame 包含原始 K 线数据
        """
        if not self._is_crypto_code(stock_code):
            raise DataFetchError(f"{stock_code} 不是有效的加密货币代码")
        
        symbol = self._convert_symbol(stock_code)
        base_code = symbol.replace('USDT', '').replace('USD', '').lower()
        
        # 尝试 Binance 主数据源
        try:
            return self._fetch_from_binance(symbol, start_date, end_date)
        except DataFetchError as e:
            logger.warning(f"[Crypto] Binance 失败: {e}，尝试 CoinGecko 备用...")
        
        # 尝试 CoinGecko 备用数据源
        try:
            return self._fetch_from_coingecko(base_code, start_date, end_date)
        except DataFetchError as e:
            logger.error(f"[Crypto] CoinGecko 也失败: {e}")
            raise DataFetchError(f"所有加密货币数据源都失败: Binance({e}), CoinGecko({e})")
    
    def _fetch_from_binance(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """从 Binance 获取 K 线数据"""
        # 转换日期为时间戳（毫秒）
        start_ts = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp() * 1000)
        end_ts = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp() * 1000)
        
        logger.info(f"[Crypto] 从 Binance 获取 {symbol} K线数据 {start_date} ~ {end_date}")
        
        # Binance K线 API
        url = "https://api.binance.com/api/v3/klines"
        params = {
            'symbol': symbol,
            'interval': '1d',  # 日线
            'startTime': start_ts,
            'endTime': end_ts,
            'limit': 1000
        }
        
        response = requests.get(url, params=params, timeout=30)
        
        if response.status_code != 200:
            error_msg = response.json().get('msg', '未知错误')
            raise DataFetchError(f"Binance API 错误: {error_msg}")
        
        data = response.json()
        
        if not data:
            raise DataFetchError(f"Binance 未返回 {symbol} 的数据")
        
        # Binance K线数据格式：
        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ])
        
        # 时间戳转日期字符串
        df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')
        
        logger.info(f"[Crypto] Binance {symbol} 获取成功，共 {len(df)} 条数据")
        return df
    
    def _fetch_from_coingecko(self, coin_id: str, start_date: str, end_date: str) -> pd.DataFrame:
        """从 CoinGecko 获取 K 线数据（备用）"""
        logger.info(f"[Crypto] 从 CoinGecko 获取 {coin_id} K线数据 {start_date} ~ {end_date}")
        
        # 币种 ID 映射（CoinGecko 使用特定 ID）
        coingecko_ids = {
            'btc': 'bitcoin',
            'eth': 'ethereum',
            'bnb': 'binancecoin',
            'xrp': 'ripple',
            'sol': 'solana',
            'doge': 'dogecoin',
            'ada': 'cardano',
            'avax': 'avalanche-2',
            'dot': 'polkadot',
            'link': 'chainlink',
            'cfx': 'conflux-token',
            'xmr': 'monero',
        }
        
        coin_gecko_id = coingecko_ids.get(coin_id, coin_id)
        
        # CoinGecko API（免费，无需 Key）
        url = f"https://api.coingecko.com/api/v3/coins/{coin_gecko_id}/market_chart"
        params = {
            'vs_currency': 'usd',
            'days': '30',  # 获取最近30天数据
            'interval': 'daily'
        }
        
        response = requests.get(url, params=params, timeout=30)
        
        if response.status_code != 200:
            raise DataFetchError(f"CoinGecko API 错误: {response.status_code}")
        
        data = response.json()
        
        if not data or 'prices' not in data:
            raise DataFetchError(f"CoinGecko 未返回 {coin_id} 的数据")
        
        # CoinGecko 返回格式：prices [[timestamp, price], ...]
        prices = data.get('prices', [])
        market_caps = data.get('market_caps', [])
        total_volumes = data.get('total_volumes', [])
        
        if not prices:
            raise DataFetchError(f"CoinGecko {coin_id} 价格数据为空")
        
        # 构建 DataFrame
        df_data = []
        for i, price_item in enumerate(prices):
            timestamp = price_item[0]  # 毫秒时间戳
            price = price_item[1]
            
            # 估算 OHLC（CoinGecko 只提供收盘价）
            # 使用前后数据估算开盘、最高、最低
            prev_price = prices[i-1][1] if i > 0 else price
            next_price = prices[i+1][1] if i < len(prices)-1 else price
            
            df_data.append({
                'timestamp': timestamp,
                'date': pd.to_datetime(timestamp, unit='ms').strftime('%Y-%m-%d'),
                'open': prev_price,
                'high': max(price, prev_price, next_price),
                'low': min(price, prev_price, next_price),
                'close': price,
                'volume': total_volumes[i][1] if i < len(total_volumes) else 0,
                'quote_volume': total_volumes[i][1] if i < len(total_volumes) else 0,
            })
        
        df = pd.DataFrame(df_data)
        
        logger.info(f"[Crypto] CoinGecko {coin_id} 获取成功，共 {len(df)} 条数据")
        return df
    
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        标准化数据为统一格式
        
        标准列：['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']
        """
        df = df.copy()
        
        # 数值类型转换
        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'quote_volume']
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 标准化列名
        df['amount'] = df['quote_volume']  # 成交额
        df['pct_chg'] = df['close'].pct_change() * 100  # 涨跌幅%
        
        # 选择标准列
        result = df[STANDARD_COLUMNS].copy()
        
        # 去除空值
        result = result.dropna(subset=['open', 'high', 'low', 'close'])
        
        return result
    
    def get_realtime_quote(self, stock_code: str) -> Optional[dict]:
        """
        获取加密货币实时行情
        
        Returns:
            Dict 包含：current, change, change_pct, volume, high, low, open
        """
        if not self._is_crypto_code(stock_code):
            return None
        
        symbol = self._convert_symbol(stock_code)
        
        try:
            # Binance 24小时统计 API
            url = "https://api.binance.com/api/v3/ticker/24hr"
            params = {'symbol': symbol}
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code != 200:
                return None
            
            data = response.json()
            
            return {
                'code': stock_code,
                'name': self.get_stock_name(stock_code),
                'current': float(data.get('lastPrice', 0)),
                'open': float(data.get('openPrice', 0)),
                'high': float(data.get('highPrice', 0)),
                'low': float(data.get('lowPrice', 0)),
                'prev_close': float(data.get('prevClosePrice', 0)),
                'change': float(data.get('priceChange', 0)),
                'change_pct': float(data.get('priceChangePercent', 0)),
                'volume': float(data.get('volume', 0)),
                'amount': float(data.get('quoteVolume', 0)),
                'source': 'binance'
            }
            
        except Exception as e:
            logger.warning(f"[Crypto] 获取 {stock_code} 实时行情失败: {e}")
            return None

    def get_chip_distribution(self, stock_code: str) -> Optional[ChipDistribution]:
        """
        获取加密货币筹码分布数据（三级降级策略）

        1. 优先使用 Coinglass API（爆仓热力图分布）
        2. 降级使用 Binance 期货数据（持仓量/多空比）
        3. 最后使用历史K线模拟（VWAP估算）

        Args:
            stock_code: 交易对代码，如 'BTCUSDT'

        Returns:
            ChipDistribution 对象，获取失败返回 None
        """
        if not self._is_crypto_code(stock_code):
            return None

        # 1. 尝试 Coinglass API
        chip_data = self._get_chip_from_coinglass(stock_code)
        if chip_data:
            return chip_data

        # 2. 尝试 Binance 期货数据
        chip_data = self._get_chip_from_binance_futures(stock_code)
        if chip_data:
            return chip_data

        # 3. 最后使用历史K线模拟
        chip_data = self._get_chip_from_historical(stock_code)
        if chip_data:
            return chip_data

        return None

    def _get_chip_from_coinglass(self, stock_code: str) -> Optional[ChipDistribution]:
        """
        从 Coinglass 获取爆仓热力图数据作为筹码分布
        Coinglass API: https://coinglass.github.io/API-Reference/#liquidation-heatmap
        """
        try:
            # 从环境变量获取 API Key
            import os
            api_key = os.getenv('COINGLASS_API_KEY')
            if not api_key:
                logger.debug("[Crypto筹码] Coinglass API Key 未配置，跳过")
                return None

            symbol = self._convert_symbol(stock_code)

            # Coinglass Liquidation Heatmap API
            url = "https://open-api.coinglass.com/public/v2/liquidation-heatmap"
            headers = {
                'coinglassSecret': api_key,
                'accept': 'application/json'
            }
            params = {
                'symbol': symbol,
                'interval': '1d',  # 日线
                'range': '30d'     # 最近30天
            }

            response = requests.get(url, headers=headers, params=params, timeout=15)

            if response.status_code != 200:
                logger.debug(f"[Crypto筹码] Coinglass API 返回 {response.status_code}")
                return None

            data = response.json()
            if not data or 'data' not in data:
                return None

            # 解析爆仓热力图数据
            heatmap_data = data['data']
            if not heatmap_data:
                return None

            # 计算爆仓集中区（类似筹码集中区）
            prices = []
            volumes = []

            for item in heatmap_data:
                price = float(item.get('price', 0))
                volume = float(item.get('liquidationVolume', 0))
                if price > 0 and volume > 0:
                    prices.append(price)
                    volumes.append(volume)

            if not prices:
                return None

            # 计算加权平均成本
            avg_cost = sum(p * v for p, v in zip(prices, volumes)) / sum(volumes)

            # 排序计算集中度
            sorted_data = sorted(zip(prices, volumes), key=lambda x: x[0])
            sorted_prices = [x[0] for x in sorted_data]
            sorted_volumes = [x[1] for x in sorted_data]

            cumsum_volumes = np.cumsum(sorted_volumes)
            total_volume = cumsum_volumes[-1]
            cumsum_ratios = cumsum_volumes / total_volume

            # 90% 筹码区间
            idx_5 = np.searchsorted(cumsum_ratios, 0.05)
            idx_95 = np.searchsorted(cumsum_ratios, 0.95)
            cost_90_low = sorted_prices[max(0, idx_5)]
            cost_90_high = sorted_prices[min(len(sorted_prices) - 1, idx_95)]
            concentration_90 = (cost_90_high - cost_90_low) / avg_cost if avg_cost > 0 else 0

            # 70% 筹码区间
            idx_15 = np.searchsorted(cumsum_ratios, 0.15)
            idx_85 = np.searchsorted(cumsum_ratios, 0.85)
            cost_70_low = sorted_prices[max(0, idx_15)]
            cost_70_high = sorted_prices[min(len(sorted_prices) - 1, idx_85)]
            concentration_70 = (cost_70_high - cost_70_low) / avg_cost if avg_cost > 0 else 0

            # 估算获利比例（当前价格 vs 平均成本）
            current_price = sorted_prices[-1] if sorted_prices else avg_cost
            profit_ratio = 0.6 if current_price > avg_cost else 0.4

            chip_data = ChipDistribution(
                code=stock_code,
                date=datetime.now().strftime('%Y-%m-%d'),
                source='coinglass_liquidation',
                profit_ratio=round(profit_ratio, 4),
                avg_cost=round(avg_cost, 2),
                cost_90_low=round(cost_90_low, 2),
                cost_90_high=round(cost_90_high, 2),
                concentration_90=round(concentration_90, 4),
                cost_70_low=round(cost_70_low, 2),
                cost_70_high=round(cost_70_high, 2),
                concentration_70=round(concentration_70, 4),
            )

            logger.info(f"[Crypto筹码-Coinglass] {stock_code}: 获利比例={profit_ratio:.1%}, "
                       f"平均成本={avg_cost:.2f}, 90%集中度={concentration_90:.2%}")

            return chip_data

        except Exception as e:
            logger.debug(f"[Crypto筹码] Coinglass 获取失败: {e}")
            return None

    def _get_chip_from_binance_futures(self, stock_code: str) -> Optional[ChipDistribution]:
        """
        从 Binance 期货数据获取持仓信息作为筹码分布代理
        使用多空比和持仓量来估算市场情绪
        """
        try:
            symbol = self._convert_symbol(stock_code)

            # 获取多空比
            long_short_url = "https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
            params = {
                'symbol': symbol,
                'period': '1d',
                'limit': 30
            }

            response = requests.get(long_short_url, params=params, timeout=10)
            if response.status_code != 200:
                return None

            ls_data = response.json()
            if not ls_data:
                return None

            # 获取持仓量
            open_interest_url = "https://fapi.binance.com/fapi/v1/openInterest"
            oi_response = requests.get(open_interest_url, params={'symbol': symbol}, timeout=10)

            # 解析多空比数据
            long_ratios = [float(d.get('longAccount', 0)) for d in ls_data if 'longAccount' in d]
            short_ratios = [float(d.get('shortAccount', 0)) for d in ls_data if 'shortAccount' in d]

            if not long_ratios:
                return None

            avg_long_ratio = sum(long_ratios) / len(long_ratios)
            avg_short_ratio = sum(short_ratios) / len(short_ratios) if short_ratios else 0.5

            # 获取当前价格
            ticker_url = "https://api.binance.com/api/v3/ticker/24hr"
            ticker_response = requests.get(ticker_url, params={'symbol': symbol}, timeout=10)

            current_price = 0
            if ticker_response.status_code == 200:
                ticker_data = ticker_response.json()
                current_price = float(ticker_data.get('lastPrice', 0))

            if current_price == 0:
                return None

            # 基于多空比估算筹码分布
            # 多头占优 -> 获利比例高（看涨情绪）
            profit_ratio = avg_long_ratio

            # 使用近期高低点作为筹码区间（简化估算）
            prices = [float(d.get('longShortRatio', 1)) * current_price for d in ls_data[:10]]
            if not prices:
                prices = [current_price * 0.9, current_price * 1.1]

            avg_cost = current_price * (1 + (avg_short_ratio - 0.5) * 0.1)  # 空头多则成本低

            # 集中度基于多空比的波动
            price_range = max(prices) - min(prices) if len(prices) > 1 else current_price * 0.05
            concentration_90 = price_range / avg_cost if avg_cost > 0 else 0.1
            concentration_70 = concentration_90 * 0.6

            cost_90_low = avg_cost * (1 - concentration_90 / 2)
            cost_90_high = avg_cost * (1 + concentration_90 / 2)
            cost_70_low = avg_cost * (1 - concentration_70 / 2)
            cost_70_high = avg_cost * (1 + concentration_70 / 2)

            chip_data = ChipDistribution(
                code=stock_code,
                date=datetime.now().strftime('%Y-%m-%d'),
                source='binance_futures',
                profit_ratio=round(profit_ratio, 4),
                avg_cost=round(avg_cost, 2),
                cost_90_low=round(cost_90_low, 2),
                cost_90_high=round(cost_90_high, 2),
                concentration_90=round(concentration_90, 4),
                cost_70_low=round(cost_70_low, 2),
                cost_70_high=round(cost_70_high, 2),
                concentration_70=round(concentration_70, 4),
            )

            logger.info(f"[Crypto筹码-Binance期货] {stock_code}: 多空比={avg_long_ratio:.1%}, "
                       f"获利比例={profit_ratio:.1%}, 集中度={concentration_90:.2%}")

            return chip_data

        except Exception as e:
            logger.debug(f"[Crypto筹码] Binance 期货获取失败: {e}")
            return None

    def _get_chip_from_historical(self, stock_code: str) -> Optional[ChipDistribution]:
        """
        使用历史K线数据模拟筹码分布（保底方案）
        使用 VWAP（成交量加权平均价格）作为平均成本
        """
        try:
            # 获取最近30天数据
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)

            df = self._fetch_raw_data(
                stock_code,
                start_date.strftime('%Y-%m-%d'),
                end_date.strftime('%Y-%m-%d')
            )

            if df is None or len(df) < 5:
                logger.warning(f"[Crypto筹码] {stock_code} 历史数据不足")
                return None

            # 标准化数据
            df = self._normalize_data(df, stock_code)

            # 当前价格和 VWAP
            current_price = df['close'].iloc[-1]
            vwap = (df['close'] * df['volume']).sum() / df['volume'].sum()

            # 获利比例
            profit_ratio = 0.6 if current_price > vwap else 0.4
            price_deviation = abs(current_price - vwap) / vwap
            profit_ratio = min(0.95, max(0.05, profit_ratio + price_deviation * 0.3))

            # 计算集中度
            prices = df['close'].values
            volumes = df['volume'].values

            sorted_indices = np.argsort(prices)
            sorted_prices = prices[sorted_indices]
            sorted_volumes = volumes[sorted_indices]

            cumsum_volumes = np.cumsum(sorted_volumes)
            total_volume = cumsum_volumes[-1]
            cumsum_ratios = cumsum_volumes / total_volume

            idx_5 = np.searchsorted(cumsum_ratios, 0.05)
            idx_95 = np.searchsorted(cumsum_ratios, 0.95)
            cost_90_low = float(sorted_prices[max(0, idx_5)])
            cost_90_high = float(sorted_prices[min(len(sorted_prices) - 1, idx_95)])
            concentration_90 = (cost_90_high - cost_90_low) / vwap if vwap > 0 else 0

            idx_15 = np.searchsorted(cumsum_ratios, 0.15)
            idx_85 = np.searchsorted(cumsum_ratios, 0.85)
            cost_70_low = float(sorted_prices[max(0, idx_15)])
            cost_70_high = float(sorted_prices[min(len(sorted_prices) - 1, idx_85)])
            concentration_70 = (cost_70_high - cost_70_low) / vwap if vwap > 0 else 0

            chip_data = ChipDistribution(
                code=stock_code,
                date=df['date'].iloc[-1],
                source='crypto_vwap',
                profit_ratio=round(profit_ratio, 4),
                avg_cost=round(vwap, 2),
                cost_90_low=round(cost_90_low, 2),
                cost_90_high=round(cost_90_high, 2),
                concentration_90=round(concentration_90, 4),
                cost_70_low=round(cost_70_low, 2),
                cost_70_high=round(cost_70_high, 2),
                concentration_70=round(concentration_70, 4),
            )

            logger.info(f"[Crypto筹码-VWAP] {stock_code}: 获利比例={profit_ratio:.1%}, "
                       f"VWAP={vwap:.2f}, 90%集中度={concentration_90:.2%}")

            return chip_data

        except Exception as e:
            logger.warning(f"[Crypto筹码] 历史K线模拟失败: {e}")
            return None
