import json
from datetime import datetime, timedelta
import pandas as pd
import base58
import os
import time
import requests
from dotenv import load_dotenv
import base64
from time import sleep
from typing import List, Dict, Any
import random
import logging
import traceback

class TokenSnapshot:
    def __init__(self):
        """Initialize the token snapshot tool using environment variables"""
        load_dotenv()
        
        # Set up logging first
        self.setup_logging()
        
        self.logger.info("Starting TokenSnapshot initialization...")
        
        # Load configuration from .env
        helius_api_key = os.getenv('HELIUS_API_KEY')
        # Update RPC endpoints list with Helius
        self.rpc_endpoints = [
            f"https://mainnet.helius-rpc.com/?api-key={helius_api_key}",
            "https://rpc.ankr.com/solana",
            "https://api.mainnet-beta.solana.com"
        ]
        self.current_rpc_index = 0
        self.rpc_url = self.rpc_endpoints[self.current_rpc_index]
        
        self.token_mint = os.getenv('TOKEN_MINT_ADDRESS')
        self.target_mcap = float(os.getenv('TARGET_MCAP_SOL', '500'))
        self.snapshot_dir = os.getenv('SNAPSHOT_DIR', 'snapshots')
        self.min_token_amount = float(os.getenv('MIN_TOKEN_AMOUNT', '1000000'))  # Added configurable minimum
        
        # More aggressive settings for Helius
        self.request_delay = 5.0         # Reduced from 30 to 5 seconds
        self.max_retries = 3             # Reduced from 8 to 3 since Helius is more reliable
        self.retry_delay = 10            # Reduced from 45 to 10 seconds
        self.jitter_range = 2.0          # Reduced from 5 to 2 seconds
        self.startup_cooldown = 10.0     # Reduced from 60 to 10 seconds
        
        # Circuit breaker settings
        self.error_threshold = 5         # Increased from 2 to 5 since Helius is more stable
        self.circuit_cooldown = 60.0     # Reduced from 300 to 60 seconds
        self.error_window = 30           # Reduced from 60 to 30 seconds
        self.error_timestamps = []
        self.circuit_broken = False
        self.circuit_break_time = None
        
        # RPC endpoint rotation settings
        self.endpoint_errors = {url: 0 for url in self.rpc_endpoints}
        self.endpoint_cooldown = 300.0   # Reduced from 600 to 300 seconds
        self.endpoint_last_error = {url: None for url in self.rpc_endpoints}
        
        # Add request tracking
        self.request_count = 0
        self.last_request_time = None
        self.error_count = 0
        
        # Log all configuration values
        self.logger.info("Configuration values:")
        self.logger.info(f"RPC URL: {self.rpc_url}")
        self.logger.info(f"Token Mint: {self.token_mint}")
        self.logger.info(f"Target Market Cap: {self.target_mcap} SOL")
        self.logger.info(f"Snapshot Directory: {self.snapshot_dir}")
        self.logger.info(f"Request Delay: {self.request_delay} seconds")
        self.logger.info(f"Max Retries: {self.max_retries}")
        self.logger.info(f"Retry Delay: {self.retry_delay} seconds")
        self.logger.info(f"Jitter Range: {self.jitter_range} seconds")
        self.logger.info(f"Startup Cooldown: {self.startup_cooldown} seconds")
        
        # Create snapshots directory if it doesn't exist
        os.makedirs(self.snapshot_dir, exist_ok=True)
        
        # Add startup cooldown
        self.logger.info(f"Starting cooldown period of {self.startup_cooldown} seconds...")
        sleep(self.startup_cooldown)
        self.logger.info("Startup cooldown completed")

    def setup_logging(self):
        """Set up logging configuration"""
        self.logger = logging.getLogger('TokenSnapshot')
        self.logger.setLevel(logging.DEBUG)
        
        # Create handlers
        console_handler = logging.StreamHandler()
        file_handler = logging.FileHandler('token_snapshot.log')
        
        # Create formatters and add it to handlers
        log_format = '%(asctime)s - %(levelname)s - %(message)s'
        formatter = logging.Formatter(log_format)
        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)
        
        # Add handlers to the logger
        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)

    def check_circuit_breaker(self) -> bool:
        """Check if circuit breaker should be engaged"""
        current_time = datetime.now()
        
        # Clear old error timestamps
        self.error_timestamps = [ts for ts in self.error_timestamps 
                               if (current_time - ts).total_seconds() < self.error_window]
        
        # Check if circuit is already broken
        if self.circuit_broken:
            if (current_time - self.circuit_break_time).total_seconds() >= self.circuit_cooldown:
                self.logger.info("Circuit breaker reset after cooldown")
                self.circuit_broken = False
                self.error_timestamps = []
            else:
                return True
        
        # Check if we need to break the circuit
        if len(self.error_timestamps) >= self.error_threshold:
            self.circuit_broken = True
            self.circuit_break_time = current_time
            self.logger.warning(f"Circuit breaker engaged. Cooling down for {self.circuit_cooldown} seconds")
            return True
        
        return False

    def rotate_rpc_endpoint(self):
        """Rotate to the next available RPC endpoint"""
        current_time = datetime.now()
        
        # Try each endpoint
        for _ in range(len(self.rpc_endpoints)):
            self.current_rpc_index = (self.current_rpc_index + 1) % len(self.rpc_endpoints)
            new_endpoint = self.rpc_endpoints[self.current_rpc_index]
            
            # Check if endpoint is in cooldown
            last_error = self.endpoint_last_error[new_endpoint]
            if last_error is None or (current_time - last_error).total_seconds() >= self.endpoint_cooldown:
                self.rpc_url = new_endpoint
                self.logger.info(f"Switched to RPC endpoint: {self.rpc_url}")
                return True
        
        self.logger.error("All RPC endpoints are in cooldown!")
        return False

    def make_rpc_request(self, method: str, params: List[Any], retry_count: int = 0) -> Dict:
        """Make a JSON RPC request with retry logic and rate limiting"""
        current_time = datetime.now()
        
        # Check circuit breaker
        if self.check_circuit_breaker():
            wait_time = (self.circuit_break_time + timedelta(seconds=self.circuit_cooldown) - current_time).total_seconds()
            self.logger.warning(f"Circuit breaker active. Waiting {wait_time:.2f} seconds")
            sleep(wait_time)
            # Rotate endpoint after circuit breaker
            self.rotate_rpc_endpoint()
        
        self.logger.info(f"Starting RPC request for method: {method}")
        self.logger.info(f"Using RPC endpoint: {self.rpc_url}")
        self.logger.info(f"Current settings: delay={self.request_delay}, retry_delay={self.retry_delay}")
        
        # Super-exponential backoff for consecutive requests
        if self.error_count > 0:
            self.request_delay = min(self.request_delay * 2.0, 120.0)  # Cap at 120 seconds
            self.logger.info(f"Adjusted request delay to {self.request_delay} due to previous errors")
        
        # Log time since last request
        if self.last_request_time:
            time_since_last = (current_time - self.last_request_time).total_seconds()
            self.logger.info(f"Time since last request: {time_since_last:.2f} seconds")
            
            # Force minimum time between requests
            if time_since_last < self.request_delay:
                additional_wait = self.request_delay - time_since_last
                self.logger.info(f"Enforcing minimum delay with additional {additional_wait:.2f} seconds wait")
                sleep(additional_wait)
        
        self.request_count += 1
        self.logger.info(f"Request #{self.request_count} - Method: {method} - Retry: {retry_count}/{self.max_retries}")
        
        # Calculate delay with super-exponential backoff and jitter
        base_sleep_time = self.request_delay * (3 ** retry_count)  # Changed to 3^n for more aggressive backoff
        jitter = random.uniform(0, self.jitter_range)
        sleep_time = base_sleep_time + jitter
        
        self.logger.info(f"Calculated sleep time: base={base_sleep_time:.2f}, jitter={jitter:.2f}, total={sleep_time:.2f}")
        self.logger.info(f"Waiting {sleep_time:.2f} seconds before request...")
        
        sleep(sleep_time)
        
        try:
            response = requests.post(self.rpc_url, 
                                   headers={'Content-Type': 'application/json'},
                                   json={
                                       "jsonrpc": "2.0",
                                       "id": 1,
                                       "method": method,
                                       "params": params
                                   })
            
            result = response.json()
            self.last_request_time = datetime.now()
            
            if 'error' in result:
                error_code = result['error'].get('code', 0)
                error_msg = result['error'].get('message', 'Unknown error')
                self.error_count += 1
                self.error_timestamps.append(current_time)
                self.endpoint_errors[self.rpc_url] += 1
                self.endpoint_last_error[self.rpc_url] = current_time
                
                self.logger.error(f"RPC error {error_code}: {error_msg}")
                self.logger.error(f"Total errors so far: {self.error_count}")
                
                if error_code in [-32005, 429]:
                    # Rotate to next endpoint on rate limit
                    if self.rotate_rpc_endpoint():
                        # If rotation successful, retry immediately with new endpoint
                        return self.make_rpc_request(method, params, retry_count)
                    elif retry_count < self.max_retries:
                        # If no rotation possible, wait and retry
                        base_wait_time = self.retry_delay * (3 ** retry_count)
                        jitter = random.uniform(0, self.jitter_range)
                        wait_time = base_wait_time + jitter
                        self.logger.warning(f"Rate limited. Waiting {wait_time:.2f} seconds before retry {retry_count + 1}/{self.max_retries}")
                        sleep(wait_time)
                        return self.make_rpc_request(method, params, retry_count + 1)
            
            return result
            
        except Exception as e:
            self.error_count += 1
            self.error_timestamps.append(current_time)
            self.logger.exception(f"RPC request failed with exception: {str(e)}")
            
            if retry_count < self.max_retries:
                wait_time = self.retry_delay * (3 ** retry_count)
                self.logger.info(f"Retrying in {wait_time:.2f} seconds. Attempt {retry_count + 1}/{self.max_retries}")
                sleep(wait_time)
                return self.make_rpc_request(method, params, retry_count + 1)
            return None

    def get_token_largest_accounts(self) -> List[Dict]:
        """Get the largest token accounts"""
        self.logger.info("Fetching largest token accounts...")
        try:
            params = [
                self.token_mint,
                {
                    "commitment": "confirmed"
                }
            ]
            
            response = self.make_rpc_request("getTokenLargestAccounts", params)
            
            if response and 'result' in response:
                accounts = response['result']['value']
                self.logger.info(f"Found {len(accounts)} large accounts")
                return accounts
            
            self.logger.warning("No accounts found in response")
            return []
            
        except Exception as e:
            self.logger.exception(f"Error fetching largest token accounts: {str(e)}")
            return []

    def get_account_info(self, address: str) -> Dict:
        """Get information about a specific token account"""
        print(f"Fetching info for account: {address}")
        try:
            params = [
                address,
                {
                    "encoding": "jsonParsed",
                    "commitment": "confirmed"
                }
            ]
            
            response = self.make_rpc_request("getAccountInfo", params)
            
            if response and 'result' in response and response['result']:
                print("Successfully fetched account info")
                return response['result']['value']
            
            print("No account info found in response")
            return None
            
        except Exception as e:
            print(f"Error fetching account info: {str(e)}")
            return None

    def get_token_accounts_by_program(self) -> List[Dict]:
        """Get token accounts using getProgramAccounts"""
        try:
            filters = [
                {
                    "dataSize": 165  # Size of token account data
                },
                {
                    "memcmp": {
                        "offset": 0,
                        "bytes": self.token_mint
                    }
                }
            ]
            
            params = [
                "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",  # Token program ID
                {
                    "encoding": "jsonParsed",
                    "filters": filters,
                    "commitment": "confirmed"
                }
            ]
            
            self.logger.info(f"Querying token accounts for mint: {self.token_mint}")
            self.logger.debug(f"Using RPC endpoint: {self.rpc_url}")
            response = self.make_rpc_request("getProgramAccounts", params)
            
            if response and 'result' in response:
                accounts = response['result']
                self.logger.info(f"Found {len(accounts)} token accounts in response")
                
                # Log first account structure for debugging
                if accounts:
                    self.logger.debug(f"Sample account structure: {json.dumps(accounts[0], indent=2)}")
                
                return accounts
            else:
                self.logger.warning(f"Unexpected response structure: {json.dumps(response, indent=2)}")
                return []
            
        except Exception as e:
            self.logger.exception(f"Error fetching token accounts: {str(e)}")
            return []

    def get_token_accounts(self) -> tuple[List[Dict], float]:
        """Query all token holders and return both filtered holders and total supply"""
        self.logger.info("\nStarting token account collection...")
        try:
            accounts = self.get_token_accounts_by_program()
            holder_balances = {}  # Dictionary to track total balance per holder
            total_supply = 0
            
            for account in accounts:
                try:
                    # Parse the account data
                    parsed_info = account['account']['data']['parsed']['info']
                    raw_balance = int(parsed_info['tokenAmount']['amount'])
                    decimals = int(parsed_info['tokenAmount']['decimals'])
                    # Adjust balance for decimals
                    balance = raw_balance / (10 ** decimals)
                    owner = parsed_info['owner']
                    
                    # Add to total supply
                    total_supply += balance
                    
                    # Aggregate balance by owner
                    holder_balances[owner] = holder_balances.get(owner, 0) + balance
                
                except (KeyError, TypeError) as e:
                    self.logger.error(f"Error parsing account data: {str(e)}")
                    continue
            
            # Create holder list after aggregating balances
            all_holders = [
                {'address': owner, 'balance': balance}
                for owner, balance in holder_balances.items()
            ]
            
            # Filter holders above minimum
            filtered_holders = [
                holder for holder in all_holders
                if holder['balance'] >= self.min_token_amount
            ]
            
            # Sort by balance
            filtered_holders.sort(key=lambda x: x['balance'], reverse=True)
            
            self.logger.info(f"\nTotal supply: {total_supply:,.2f}")
            self.logger.info(f"Unique holders (after aggregating): {len(holder_balances)}")
            self.logger.info(f"Holders with >= {self.min_token_amount:,} tokens: {len(filtered_holders)}")
            
            # Log some sample data
            if filtered_holders:
                self.logger.info("\nTop 5 holders:")
                for holder in filtered_holders[:5]:
                    self.logger.info(f"Address: {holder['address']}, Balance: {holder['balance']:,.2f}")
            
            return filtered_holders, total_supply
            
        except Exception as e:
            self.logger.exception(f"Error in get_token_accounts: {str(e)}")
            return [], 0

    def get_token_sol_price(self) -> float:
        """Calculate token price in SOL based on current market data"""
        # Market cap is $43,000 and SOL price is $207.22
        # Total supply is 983,819,627.71 tokens
        # So: token_price_in_usd = $43,000 / 983,819,627.71 ≈ $0.0000437 per token
        # token_price_in_sol = $0.0000437 / $207.22 ≈ 0.000000211 SOL per token
        return 0.000000211  # SOL per token

    def calculate_market_cap(self, total_supply: float) -> tuple[float, float]:
        """Calculate total SOL volume and progress"""
        try:
            # Use the quick check method to get current progress
            return self.quick_market_cap_check()
        except Exception as e:
            self.logger.error(f"Error calculating SOL volume: {str(e)}")
            return None

    def determine_snapshot_interval(self, progress: float) -> int:
        """Determine snapshot interval based on bonding progress"""
        if progress >= 99:
            return 300  # Every 5 minutes
        elif progress >= 97:
            return 1800  # Every 30 minutes
        elif progress >= 95:
            return 3600  # Every hour
        elif progress >= 90:
            return 14400  # Every 4 hours
        elif progress >= 85:
            return 86400  # Every 24 hours
        else:
            return None  # No regular snapshots below 85%

    def take_snapshot(self) -> Dict:
        """Take a snapshot of all token holders and their balances"""
        self.logger.info("\nTaking new snapshot...")
        try:
            timestamp = datetime.now()
            holders, total_supply = self.get_token_accounts()  # Get both holders and total supply
            
            if not holders:
                self.logger.warning("No holders found in snapshot")
                return None
                
            self.logger.info("Processing holder data...")
            # Create DataFrame for filtered holders
            df = pd.DataFrame(holders)
            
            # Group by address and sum balances (in case of multiple accounts)
            df = df.groupby('address')['balance'].sum().reset_index()
            
            # Sort by balance descending
            df = df.sort_values('balance', ascending=False)
            
            # Add timestamp
            df['timestamp'] = timestamp.isoformat()
            
            # Log some statistics
            self.logger.info(f"Total unique holders above minimum: {len(df)}")
            self.logger.info(f"Top 5 holders:")
            for _, row in df.head().iterrows():
                self.logger.info(f"Address: {row['address']}, Balance: {row['balance']:,.2f}")
            
            # Calculate market cap using TOTAL supply
            market_cap_info = self.calculate_market_cap(total_supply)
            if market_cap_info:
                sol_volume, progress = market_cap_info
            else:
                sol_volume, progress = 0, 0
            
            self.logger.info(f"Total supply: {total_supply:,.2f}")
            self.logger.info(f"SOL Volume: {sol_volume:.2f}")
            self.logger.info(f"Progress: {progress:.2f}%")
            
            # Save snapshot with timestamp
            filename = f"{self.snapshot_dir}/snapshot_{timestamp.strftime('%Y%m%d_%H%M%S')}"
            df.to_csv(f"{filename}.csv", index=False)
            
            snapshot_info = {
                'timestamp': timestamp.isoformat(),
                'total_holders': int(len(df)),
                'total_supply': float(total_supply),
                'sol_volume': float(sol_volume),
                'progress': float(progress),
                'target_reached': bool(progress >= 100)
            }
            
            with open(f"{filename}_info.json", 'w') as f:
                json.dump(snapshot_info, f, indent=2)
            
            self.logger.info("Snapshot saved successfully")
            return snapshot_info
            
        except Exception as e:
            self.logger.exception(f"Error taking snapshot: {str(e)}")
            return None

    def quick_market_cap_check(self) -> tuple[float, float]:
        """Check bonding progress using DexScreener"""
        try:
            dexscreener_url = f"https://api.dexscreener.com/latest/dex/tokens/{self.token_mint}"
            response = requests.get(dexscreener_url)
            data = response.json()
            
            if data and 'pairs' in data and len(data['pairs']) > 0:
                pair = data['pairs'][0]
                
                if 'moonshot' in pair and 'progress' in pair['moonshot']:
                    progress = float(pair['moonshot']['progress'])
                    sol_volume = (progress / 100) * self.target_mcap
                    
                    self.logger.info(f"\nProgress check at {datetime.now()}")
                    self.logger.info(f"Progress to target: {progress:.1f}%")
                    self.logger.info(f"Estimated SOL volume: {sol_volume:.2f} SOL")
                    self.logger.info(f"Distance to target: {self.target_mcap - sol_volume:.2f} SOL")
                    
                    return sol_volume, progress
                
            return None
        except Exception as e:
            self.logger.error(f"Error in progress check: {str(e)}")
            return None

    def monitor_market_cap(self):
        """Continuously monitor bonding progress and take snapshots at appropriate intervals"""
        self.logger.info(f"Starting bonding progress monitoring. Target: {self.target_mcap} SOL")
        
        # Take initial snapshot regardless of progress
        initial_snapshot = self.take_snapshot()
        if initial_snapshot:
            self.logger.info("Initial snapshot taken successfully")
        
        last_snapshot_time = datetime.now()
        next_snapshot_time = None
        last_check_time = datetime.now()
        check_interval = 300  # Check progress every 5 minutes
        last_progress = None  # Track last progress percentage
        thresholds = [85, 90, 95, 97, 99]  # Progress thresholds
        last_threshold = None  # Track last threshold crossed
        
        while True:
            try:
                current_time = datetime.now()
                
                # Do progress check every 5 minutes
                if (current_time - last_check_time).total_seconds() >= check_interval:
                    progress_info = self.quick_market_cap_check()
                    last_check_time = current_time
                    
                    if progress_info:
                        sol_volume, progress = progress_info
                        
                        # Check if we've crossed any thresholds
                        current_threshold = None
                        for threshold in thresholds:
                            if progress >= threshold:
                                current_threshold = threshold
                                continue
                            break
                        
                        # Take snapshot if we've crossed a threshold in either direction
                        if (last_threshold is not None and current_threshold != last_threshold) or \
                           (last_threshold is None and current_threshold is not None):
                            self.logger.info(f"Progress threshold crossed: {current_threshold}% - Taking snapshot...")
                            snapshot_info = self.take_snapshot()
                            if snapshot_info:
                                last_snapshot_time = current_time
                                last_threshold = current_threshold
                        
                        # Determine next snapshot interval based on progress
                        interval = self.determine_snapshot_interval(progress)
                        
                        if interval:
                            # Update next snapshot time if needed
                            if next_snapshot_time is None or current_time >= next_snapshot_time:
                                next_snapshot_time = current_time + timedelta(seconds=interval)
                                self.logger.info(f"Next scheduled snapshot at: {next_snapshot_time.strftime('%Y-%m-%d %H:%M:%S')}")
                            
                            # Take a snapshot if it's time
                            if current_time >= next_snapshot_time:
                                self.logger.info("Taking scheduled snapshot...")
                                snapshot_info = self.take_snapshot()
                                if snapshot_info:
                                    last_snapshot_time = current_time
                                    next_snapshot_time = current_time + timedelta(seconds=interval)
                                    self.logger.info(f"Next scheduled snapshot at: {next_snapshot_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    
                    # Always show when next snapshot is scheduled
                    if next_snapshot_time:
                        time_to_next = (next_snapshot_time - current_time).total_seconds()
                        self.logger.info(f"Time until next snapshot: {time_to_next/60:.1f} minutes")
                    
                    # Check if we've reached 100%
                    if progress >= 100:
                        self.logger.info("🎯 BONDING TARGET REACHED! Taking final snapshot...")
                        final_snapshot = self.take_snapshot()
                        if final_snapshot:
                            self.logger.info("Final snapshot saved. Monitoring stopped.")
                        break
                    
                    last_progress = progress
            
                # Sleep for a short interval to prevent CPU overuse
                time.sleep(30)  # Check every 30 seconds
                    
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {str(e)}")
                self.logger.error(f"Full error: {traceback.format_exc()}")
                time.sleep(30)  # Wait before retrying

def main():
    # Create .env file template if it doesn't exist
    if not os.path.exists('.env'):
        with open('.env', 'w') as f:
            f.write("""# Solana Configuration
HELIUS_API_KEY=your_helius_api_key_here
TOKEN_MINT_ADDRESS=your_token_mint_address
TARGET_MCAP_SOL=500
SNAPSHOT_DIR=snapshots
MIN_TOKEN_AMOUNT=1000000
""")
        print("Created .env template file. Please fill in your configuration details.")
        return

    snapshot = TokenSnapshot()
    snapshot.monitor_market_cap()

if __name__ == "__main__":
    main()
