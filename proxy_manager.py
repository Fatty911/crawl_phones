"""
代理管理器 - 支持多机场订阅、节点过滤、负载均衡、Clash集成
"""
import os
import json
import base64
import random
import time
import requests
import re
import subprocess
import signal
from typing import List, Dict, Optional, Set
from urllib.parse import urlparse
from datetime import datetime


def redact_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.netloc:
        return "<invalid-url>"
    return f"{parsed.scheme}://{parsed.netloc}/***"


class ProxyManager:
    def __init__(self, config_file: str = "proxies.json"):
        self.config_file = config_file
        self.proxies: List[Dict] = []
        self.proxy_stats: Dict[str, Dict] = {}
        self.exclude_keywords: Set[str] = set()
        self.subscriptions: List[str] = []
        self.current_index = 0
        self.clash_process = None
        self.clash_config = "/root/.config/mihomo/config.yaml"
        self.clash_mixed_port = 7890
        self.clash_socks_port = 7891
        self.clash_api = "http://127.0.0.1:9090"
        self.load_config()

    def load_config(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                self.proxies = config.get('proxies', [])
                self.proxy_stats = config.get('stats', {})
                self.exclude_keywords = set(config.get('exclude_keywords', []))
                self.subscriptions = config.get('subscriptions', [])

    def save_config(self):
        config = {
            'proxies': self.proxies,
            'stats': self.proxy_stats,
            'exclude_keywords': list(self.exclude_keywords),
            'subscriptions': self.subscriptions,
            'last_updated': datetime.now().isoformat()
        }
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    def add_exclude_keyword(self, keyword: str):
        """添加排除关键字"""
        self.exclude_keywords.add(keyword.lower())
        self.save_config()
        print(f"已添加排除关键字: {keyword}")

    def remove_exclude_keyword(self, keyword: str):
        """移除排除关键字"""
        self.exclude_keywords.discard(keyword.lower())
        self.save_config()
        print(f"已移除排除关键字: {keyword}")

    def set_exclude_keywords(self, keywords: List[str]):
        """设置排除关键字列表"""
        self.exclude_keywords = set(k.lower() for k in keywords)
        self.save_config()
        print(f"已设置 {len(keywords)} 个排除关键字")

    def should_exclude(self, proxy_name: str) -> bool:
        """检查节点是否应该被排除"""
        name_lower = proxy_name.lower()
        for keyword in self.exclude_keywords:
            if keyword in name_lower:
                return True
        return False

    def add_subscription(self, url: str):
        """添加订阅URL"""
        if url not in self.subscriptions:
            self.subscriptions.append(url)
            self.save_config()
            print(f"已添加订阅: {redact_url(url)}")

    def remove_subscription(self, url: str):
        """移除订阅URL"""
        if url in self.subscriptions:
            self.subscriptions.remove(url)
            self.save_config()
            print(f"已移除订阅: {redact_url(url)}")

    def clear_proxies(self):
        """清空所有代理"""
        self.proxies = []
        self.proxy_stats = {}
        self.save_config()
        print("已清空所有代理")

    def add_http_proxy(self, name: str, host: str, port: int, 
                       username: str = "", password: str = ""):
        """添加HTTP代理"""
        if self.should_exclude(name):
            print(f"跳过被排除的节点: {name}")
            return False
        
        proxy = {
            'name': name,
            'type': 'http',
            'host': host,
            'port': port,
            'username': username,
            'password': password
        }
        
        # 检查是否已存在
        for p in self.proxies:
            if p['name'] == name:
                print(f"节点已存在: {name}")
                return False
        
        self.proxies.append(proxy)
        self.proxy_stats[name] = {'success': 0, 'fail': 0, 'last_used': 0}
        self.save_config()
        return True

    def add_socks5_proxy(self, name: str, host: str, port: int,
                         username: str = "", password: str = ""):
        """添加SOCKS5代理"""
        if self.should_exclude(name):
            print(f"跳过被排除的节点: {name}")
            return False
        
        proxy = {
            'name': name,
            'type': 'socks5',
            'host': host,
            'port': port,
            'username': username,
            'password': password
        }
        
        for p in self.proxies:
            if p['name'] == name:
                return False
        
        self.proxies.append(proxy)
        self.proxy_stats[name] = {'success': 0, 'fail': 0, 'last_used': 0}
        self.save_config()
        return True

    def parse_v2ray_subscription(self, subscription_url: str) -> List[Dict]:
        """解析V2Ray订阅链接"""
        try:
            print(f"正在获取订阅: {redact_url(subscription_url)}")
            resp = requests.get(subscription_url, timeout=30)
            if resp.status_code != 200:
                print(f"获取订阅失败: HTTP {resp.status_code}")
                return []
            
            content = base64.b64decode(resp.text).decode('utf-8')
            proxies = []
            added = 0
            excluded = 0
            
            for line in content.strip().split('\n'):
                line = line.strip()
                proxy = None
                
                if line.startswith('vmess://'):
                    proxy = self._parse_vmess(line)
                elif line.startswith('ss://'):
                    proxy = self._parse_ss(line)
                elif line.startswith('trojan://'):
                    proxy = self._parse_trojan(line)
                elif line.startswith('vless://'):
                    proxy = self._parse_vless(line)
                
                if proxy:
                    if self.should_exclude(proxy['name']):
                        excluded += 1
                        continue
                    
                    # 检查重复
                    if not any(p['name'] == proxy['name'] for p in self.proxies):
                        proxies.append(proxy)
                        self.proxy_stats[proxy['name']] = {'success': 0, 'fail': 0, 'last_used': 0}
                        added += 1
            
            self.proxies.extend(proxies)
            self.save_config()
            print(f"解析完成: 新增 {added} 个节点, 排除 {excluded} 个节点")
            return proxies
            
        except Exception as e:
            print(f"解析订阅失败: {e}")
            return []

    def _parse_vmess(self, line: str) -> Optional[Dict]:
        """解析VMess链接"""
        try:
            vmess_data = json.loads(base64.b64decode(line[8:]).decode('utf-8'))
            return {
                'name': vmess_data.get('ps', 'vmess'),
                'type': 'vmess',
                'host': vmess_data.get('add'),
                'port': int(vmess_data.get('port', 443)),
                'uuid': vmess_data.get('id'),
                'alterId': int(vmess_data.get('aid', 0)),
                'cipher': vmess_data.get('scy', 'auto'),
                'network': vmess_data.get('net', 'tcp'),
                'tls': vmess_data.get('tls', '') == 'tls',
            }
        except Exception as e:
            print(f"解析VMess失败: {e}")
            return None

    def _parse_ss(self, line: str) -> Optional[Dict]:
        """解析SS链接"""
        try:
            match = re.match(r'ss://([^@]+)@([^:]+):(\d+)(?:#(.+))?', line)
            if match:
                userinfo = base64.b64decode(match.group(1)).decode('utf-8')
                cipher, password = userinfo.split(':', 1)
                return {
                    'name': match.group(4) or 'ss',
                    'type': 'ss',
                    'host': match.group(2),
                    'port': int(match.group(3)),
                    'cipher': cipher,
                    'password': password,
                }
        except Exception as e:
            print(f"解析SS失败: {e}")
        return None

    def _parse_trojan(self, line: str) -> Optional[Dict]:
        """解析Trojan链接"""
        try:
            parsed = urlparse(line)
            return {
                'name': parsed.fragment or 'trojan',
                'type': 'trojan',
                'host': parsed.hostname,
                'port': parsed.port,
                'password': parsed.username,
            }
        except Exception as e:
            print(f"解析Trojan失败: {e}")
        return None

    def _parse_vless(self, line: str) -> Optional[Dict]:
        """解析VLESS链接"""
        try:
            parsed = urlparse(line)
            return {
                'name': parsed.fragment or 'vless',
                'type': 'vless',
                'host': parsed.hostname,
                'port': parsed.port,
                'uuid': parsed.username,
            }
        except Exception as e:
            print(f"解析VLESS失败: {e}")
        return None

    def parse_clash_config(self, config_text: str) -> List[Dict]:
        """解析Clash配置文件"""
        try:
            import yaml
            config = yaml.safe_load(config_text)
            proxies = []
            added = 0
            excluded = 0
            
            for p in config.get('proxies', []):
                name = p.get('name', 'unnamed')
                
                if self.should_exclude(name):
                    excluded += 1
                    continue
                
                proxy = {
                    'name': name,
                    'type': p.get('type'),
                    'host': p.get('server'),
                    'port': p.get('port'),
                }
                
                if p.get('type') == 'ss':
                    proxy.update({
                        'cipher': p.get('cipher'),
                        'password': p.get('password'),
                    })
                elif p.get('type') == 'vmess':
                    proxy.update({
                        'uuid': p.get('uuid'),
                        'alterId': p.get('alterId', 0),
                        'cipher': p.get('cipher', 'auto'),
                    })
                elif p.get('type') == 'trojan':
                    proxy.update({
                        'password': p.get('password'),
                    })
                elif p.get('type') == 'socks5':
                    proxy.update({
                        'username': p.get('username'),
                        'password': p.get('password'),
                    })
                
                if proxy['host'] and proxy['port']:
                    if not any(pr['name'] == name for pr in self.proxies):
                        proxies.append(proxy)
                        self.proxy_stats[name] = {'success': 0, 'fail': 0, 'last_used': 0}
                        added += 1
            
            self.proxies.extend(proxies)
            self.save_config()
            print(f"解析完成: 新增 {added} 个节点, 排除 {excluded} 个节点")
            return proxies
            
        except Exception as e:
            print(f"解析Clash配置失败: {e}")
            return []

    def parse_all_subscriptions(self):
        """解析所有订阅"""
        if not self.subscriptions:
            print("没有订阅URL")
            return
        
        print(f"开始解析 {len(self.subscriptions)} 个订阅...")
        total = 0
        
        for url in self.subscriptions:
            proxies = self.parse_v2ray_subscription(url)
            total += len(proxies)
        
        print(f"总共新增 {total} 个节点")
        print(f"当前可用节点: {len(self.proxies)} 个")

    def refresh_proxies(self):
        """刷新所有代理（清空后重新解析订阅）"""
        print("刷新代理...")
        self.clear_proxies()
        self.parse_all_subscriptions()

    def get_proxy(self, strategy: str = 'round_robin') -> Optional[Dict]:
        """获取代理"""
        if not self.proxies:
            return None
        
        # 过滤掉失败次数过多的代理
        available = []
        for p in self.proxies:
            stats = self.proxy_stats.get(p['name'], {})
            fail_rate = stats.get('fail', 0) / max(stats.get('success', 0) + stats.get('fail', 0), 1)
            if fail_rate < 0.8:  # 失败率小于80%
                available.append(p)
        
        if not available:
            print("警告: 所有代理失败率过高，使用全部代理")
            available = self.proxies
        
        if strategy == 'random':
            return random.choice(available)
        
        elif strategy == 'round_robin':
            proxy = available[self.current_index % len(available)]
            self.current_index += 1
            return proxy
        
        elif strategy == 'least_used':
            min_use = float('inf')
            selected = None
            for p in available:
                stats = self.proxy_stats.get(p['name'], {})
                use_count = stats.get('success', 0) + stats.get('fail', 0)
                if use_count < min_use:
                    min_use = use_count
                    selected = p
            return selected
        
        elif strategy == 'best_performance':
            best_score = -1
            selected = None
            for p in available:
                stats = self.proxy_stats.get(p['name'], {})
                success = stats.get('success', 0)
                fail = stats.get('fail', 0)
                total = success + fail
                score = success / total if total > 0 else 0.5
                if score > best_score:
                    best_score = score
                    selected = p
            return selected or available[0]
        
        return available[0]

    def report_success(self, proxy_name: str):
        """报告成功"""
        if proxy_name in self.proxy_stats:
            self.proxy_stats[proxy_name]['success'] += 1
            self.proxy_stats[proxy_name]['last_used'] = time.time()
            self.save_config()

    def report_failure(self, proxy_name: str):
        """报告失败"""
        if proxy_name in self.proxy_stats:
            self.proxy_stats[proxy_name]['fail'] += 1
            self.save_config()

    def get_requests_proxies(self, proxy: Dict) -> Dict[str, str]:
        """转换为requests库可用的代理格式"""
        if not proxy:
            return {}
        
        host = proxy.get('host')
        port = proxy.get('port')
        
        if not host or not port:
            return {}
        
        auth = ""
        if proxy.get('username') and proxy.get('password'):
            auth = f"{proxy['username']}:{proxy['password']}@"
        
        proxy_url = f"{host}:{port}"
        if auth:
            proxy_url = f"{auth}{proxy_url}"
        
        proxy_type = proxy.get('type', 'http')
        
        if proxy_type == 'http':
            return {'http': f'http://{proxy_url}', 'https': f'http://{proxy_url}'}
        elif proxy_type == 'socks5':
            return {'http': f'socks5://{proxy_url}', 'https': f'socks5://{proxy_url}'}
        else:
            print(f"注意: {proxy_type} 类型代理需要本地客户端转换")
            return {}
    
    def generate_clash_config(self) -> bool:
        """生成Clash配置文件"""
        try:
            from generate_clash_config import ClashConfigGenerator
            generator = ClashConfigGenerator(self.clash_config)
            return generator.generate_and_save(
                subscriptions=self.subscriptions,
                exclude_keywords=list(self.exclude_keywords),
                output_path=self.clash_config
            )
        except Exception as e:
            print(f"生成Clash配置失败: {e}")
            return False
    
    def start_clash(self, generate_config: bool = True) -> bool:
        """启动Clash进程"""
        if self.check_clash_running():
            print("Clash已在运行中")
            return True
        
        if not self.subscriptions:
            print("没有订阅URL，无法启动Clash")
            return False
        
        if generate_config:
            if not self.generate_clash_config():
                print("生成配置失败")
                return False
        
        if not os.path.exists(self.clash_config):
            print(f"Clash配置文件不存在: {self.clash_config}")
            return False
        
        try:
            self.clash_process = subprocess.Popen(
                ['mihomo', '-d', os.path.dirname(self.clash_config), '-f', self.clash_config],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid
            )
            
            time.sleep(2)
            
            if self.clash_process.poll() is None:
                print(f"Clash启动成功 (PID: {self.clash_process.pid})")
                print(f"HTTP代理: http://127.0.0.1:{self.clash_mixed_port}")
                print(f"SOCKS5代理: socks5://127.0.0.1:{self.clash_socks_port}")
                return True
            else:
                stderr = self.clash_process.stderr.read().decode('utf-8')
                print(f"Clash启动失败: {stderr}")
                return False
                
        except FileNotFoundError:
            print("mihomo未安装，请使用Docker或手动安装")
            return False
        except Exception as e:
            print(f"启动Clash失败: {e}")
            return False
    
    def stop_clash(self):
        """停止Clash进程"""
        if self.clash_process:
            try:
                os.killpg(os.getpgid(self.clash_process.pid), signal.SIGTERM)
                self.clash_process = None
                print("Clash已停止")
            except Exception as e:
                print(f"停止Clash失败: {e}")
        else:
            try:
                result = subprocess.run(['pgrep', '-f', 'mihomo'], capture_output=True, text=True)
                if result.stdout.strip():
                    pids = result.stdout.strip().split('\n')
                    for pid in pids:
                        os.kill(int(pid), signal.SIGTERM)
                    print(f"已停止 {len(pids)} 个mihomo进程")
            except (OSError, ProcessLookupError):
                pass
    
    def check_clash_running(self) -> bool:
        """检查Clash是否运行"""
        try:
            resp = requests.get(f"{self.clash_api}/version", timeout=2)
            return resp.status_code == 200
        except (requests.RequestException, OSError):
            pass
        
        if self.clash_process and self.clash_process.poll() is None:
            return True
        
        try:
            result = subprocess.run(['pgrep', '-f', 'mihomo'], capture_output=True, text=True)
            return bool(result.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            return False
    
    def get_clash_proxies(self) -> Dict:
        """通过Clash API获取代理列表"""
        try:
            resp = requests.get(f"{self.clash_api}/proxies", timeout=5)
            if resp.status_code == 200:
                return resp.json().get('proxies', {})
        except Exception as e:
            print(f"获取Clash代理失败: {e}")
        return {}
    
    def select_clash_proxy(self, group: str = "PROXY", proxy_name: str = "AUTO") -> bool:
        """通过Clash API选择代理"""
        try:
            resp = requests.put(
                f"{self.clash_api}/proxies/{group}",
                json={"name": proxy_name},
                timeout=5
            )
            return resp.status_code == 204 or resp.status_code == 200
        except Exception as e:
            print(f"选择代理失败: {e}")
            return False
    
    def get_clash_delay(self, proxy_name: str, url: str = "http://www.gstatic.com/generate_204") -> int:
        """测试Clash代理延迟"""
        try:
            resp = requests.get(
                f"{self.clash_api}/proxies/{proxy_name}/delay",
                params={"url": url, "timeout": 5000},
                timeout=10
            )
            if resp.status_code == 200:
                return resp.json().get('delay', -1)
        except (requests.RequestException, OSError):
            pass
        return -1
    
    def get_clash_local_proxy(self) -> Dict[str, str]:
        """获取Clash本地代理配置（用于requests）"""
        if self.check_clash_running():
            return {
                'http': f'http://127.0.0.1:{self.clash_mixed_port}',
                'https': f'http://127.0.0.1:{self.clash_mixed_port}'
            }
        return {}
    
    def auto_select_best_proxy(self) -> Optional[str]:
        """自动选择最快代理"""
        proxies = self.get_clash_proxies()
        if not proxies:
            return None
        
        auto_group = proxies.get('AUTO', {})
        if auto_group:
            now = auto_group.get('now', 'AUTO')
            if now and now != 'DIRECT':
                return now
        
        best_name = None
        best_delay = float('inf')
        
        for name, info in proxies.items():
            if name in ['DIRECT', 'REJECT', 'GLOBAL', 'PROXY', 'AUTO']:
                continue
            
            delay = info.get('history', [{}])[-1].get('delay', 0) if info.get('history') else 0
            if 0 < delay < best_delay:
                best_delay = delay
                best_name = name
        
        if best_name:
            self.select_clash_proxy("AUTO", best_name)
            print(f"已选择最快代理: {best_name} ({best_delay}ms)")
        
        return best_name

    def list_proxies(self, limit: int = 50) -> str:
        """列出代理"""
        result = []
        result.append(f"总共 {len(self.proxies)} 个代理节点\n")
        result.append(f"排除关键字: {', '.join(self.exclude_keywords) or '无'}\n")
        result.append(f"订阅数量: {len(self.subscriptions)}\n")
        result.append("-" * 80)
        
        for i, p in enumerate(self.proxies[:limit]):
            stats = self.proxy_stats.get(p['name'], {})
            success = stats.get('success', 0)
            fail = stats.get('fail', 0)
            total = success + fail
            rate = f"{success}/{total}" if total > 0 else "N/A"
            
            result.append(f"\n{i+1}. {p['name']}")
            result.append(f"   类型: {p['type']} | 地址: {p.get('host', 'N/A')}:{p.get('port', 'N/A')}")
            result.append(f"   统计: {rate}")
        
        if len(self.proxies) > limit:
            result.append(f"\n... 还有 {len(self.proxies) - limit} 个节点未显示")
        
        return '\n'.join(result)

    def get_stats(self) -> str:
        """获取统计信息"""
        total = len(self.proxies)
        if total == 0:
            return "没有代理节点"
        
        total_success = sum(s.get('success', 0) for s in self.proxy_stats.values())
        total_fail = sum(s.get('fail', 0) for s in self.proxy_stats.values())
        
        good_proxies = sum(1 for p in self.proxies 
                          if self.proxy_stats.get(p['name'], {}).get('success', 0) > 
                          self.proxy_stats.get(p['name'], {}).get('fail', 0))
        
        return f"""代理统计:
  总节点数: {total}
  可用节点: {good_proxies}
  排除关键字: {len(self.exclude_keywords)} 个
  订阅数量: {len(self.subscriptions)} 个
  总成功: {total_success}
  总失败: {total_fail}
  成功率: {total_success/(total_success+total_fail)*100:.1f}%""" if (total_success+total_fail) > 0 else "暂无使用记录"


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='代理管理工具')
    
    # 添加代理
    parser.add_argument('--add-http', nargs=4, metavar=('NAME', 'HOST', 'PORT', 'USER:PASS'), 
                       help='添加HTTP代理')
    parser.add_argument('--add-socks5', nargs=4, metavar=('NAME', 'HOST', 'PORT', 'USER:PASS'), 
                       help='添加SOCKS5代理')
    
    # 订阅管理
    parser.add_argument('--add-sub', type=str, help='添加订阅URL')
    parser.add_argument('--remove-sub', type=str, help='移除订阅URL')
    parser.add_argument('--list-subs', action='store_true', help='列出所有订阅')
    parser.add_argument('--refresh', action='store_true', help='刷新所有订阅')
    
    # 排除关键字
    parser.add_argument('--exclude', type=str, help='添加排除关键字（逗号分隔）')
    parser.add_argument('--remove-exclude', type=str, help='移除排除关键字')
    parser.add_argument('--list-exclude', action='store_true', help='列出排除关键字')
    
    # 解析
    parser.add_argument('--sub', type=str, help='解析单个订阅URL')
    parser.add_argument('--clash', type=str, help='解析Clash配置文件路径')
    
    # Clash管理
    parser.add_argument('--start-clash', action='store_true', help='启动Clash')
    parser.add_argument('--stop-clash', action='store_true', help='停止Clash')
    parser.add_argument('--clash-status', action='store_true', help='查看Clash状态')
    parser.add_argument('--clash-proxies', action='store_true', help='列出Clash代理')
    parser.add_argument('--select-proxy', type=str, metavar='NAME', help='选择Clash代理')
    parser.add_argument('--auto-select', action='store_true', help='自动选择最快代理')
    parser.add_argument('--test-delay', type=str, metavar='NAME', help='测试代理延迟')
    
    # 查看
    parser.add_argument('--list', action='store_true', help='列出所有代理')
    parser.add_argument('--stats', action='store_true', help='显示统计信息')
    parser.add_argument('--test', type=int, help='测试前N个代理')
    parser.add_argument('--clear', action='store_true', help='清空所有代理')
    
    args = parser.parse_args()
    
    pm = ProxyManager()

    if args.add_http:
        name, host, port = args.add_http[:3]
        auth = args.add_http[3].split(':') if ':' in args.add_http[3] else []
        pm.add_http_proxy(name, host, int(port), auth[0] if len(auth) > 0 else "", auth[1] if len(auth) > 1 else "")
    
    elif args.add_socks5:
        name, host, port = args.add_socks5[:3]
        auth = args.add_socks5[3].split(':') if ':' in args.add_socks5[3] else []
        pm.add_socks5_proxy(name, host, int(port), auth[0] if len(auth) > 0 else "", auth[1] if len(auth) > 1 else "")
    
    elif args.add_sub:
        pm.add_subscription(args.add_sub)
    
    elif args.remove_sub:
        pm.remove_subscription(args.remove_sub)
    
    elif args.list_subs:
        print(f"订阅列表 ({len(pm.subscriptions)} 个):")
        for i, url in enumerate(pm.subscriptions, 1):
            print(f"  {i}. {url}")
    
    elif args.refresh:
        pm.refresh_proxies()
    
    elif args.exclude:
        for keyword in args.exclude.split(','):
            pm.add_exclude_keyword(keyword.strip())
    
    elif args.remove_exclude:
        pm.remove_exclude_keyword(args.remove_exclude)
    
    elif args.list_exclude:
        print(f"排除关键字 ({len(pm.exclude_keywords)} 个):")
        for kw in pm.exclude_keywords:
            print(f"  - {kw}")
    
    elif args.sub:
        pm.parse_v2ray_subscription(args.sub)
    
    elif args.clash:
        with open(args.clash, 'r', encoding='utf-8') as f:
            pm.parse_clash_config(f.read())
    
    elif args.start_clash:
        if pm.start_clash():
            print("\n代理已就绪!")
            print(f"HTTP代理: http://127.0.0.1:{pm.clash_mixed_port}")
            print(f"SOCKS5代理: socks5://127.0.0.1:{pm.clash_socks_port}")
        else:
            print("启动失败")
    
    elif args.stop_clash:
        pm.stop_clash()
    
    elif args.clash_status:
        if pm.check_clash_running():
            print("Clash运行中")
            try:
                resp = requests.get(f"{pm.clash_api}/version", timeout=2)
                print(f"版本: {resp.json()}")
            except (requests.RequestException, OSError):
                pass
        else:
            print("Clash未运行")
    
    elif args.clash_proxies:
        proxies = pm.get_clash_proxies()
        if proxies:
            print(f"Clash代理列表 ({len(proxies)} 个):")
            for name, info in proxies.items():
                if name in ['DIRECT', 'REJECT', 'GLOBAL']:
                    continue
                proxy_type = info.get('type', 'unknown')
                delay = info.get('history', [{}])[-1].get('delay', 'N/A') if info.get('history') else 'N/A'
                alive = '✓' if delay != 'N/A' and delay > 0 else '✗'
                print(f"  {alive} {name} ({proxy_type}) - {delay}ms")
        else:
            print("无法获取代理列表，请确保Clash正在运行")
    
    elif args.select_proxy:
        if pm.select_clash_proxy("PROXY", args.select_proxy):
            print(f"已选择代理: {args.select_proxy}")
        else:
            print("选择失败")
    
    elif args.auto_select:
        best = pm.auto_select_best_proxy()
        if best:
            print(f"已自动选择: {best}")
        else:
            print("自动选择失败")
    
    elif args.test_delay:
        delay = pm.get_clash_delay(args.test_delay)
        if delay > 0:
            print(f"延迟: {delay}ms")
        else:
            print("测试失败")
    
    elif args.list:
        print(pm.list_proxies())
    
    elif args.stats:
        print(pm.get_stats())
    
    elif args.test:
        print(f"测试前 {args.test} 个代理...")
        for p in pm.proxies[:args.test]:
            print(f"\n测试 {p['name']}...")
            proxies = pm.get_requests_proxies(p)
            if proxies:
                try:
                    resp = requests.get('https://httpbin.org/ip', proxies=proxies, timeout=10)
                    if resp.status_code == 200:
                        print(f"  ✓ 成功: {resp.json()}")
                        pm.report_success(p['name'])
                    else:
                        print(f"  ✗ 失败: HTTP {resp.status_code}")
                        pm.report_failure(p['name'])
                except Exception as e:
                    print(f"  ✗ 异常: {e}")
                    pm.report_failure(p['name'])
            else:
                print(f"  - 跳过: 需要 {p['type']} 本地客户端")
    
    elif args.clear:
        confirm = input("确定要清空所有代理吗? (y/N): ")
        if confirm.lower() == 'y':
            pm.clear_proxies()
    
    else:
        parser.print_help()
