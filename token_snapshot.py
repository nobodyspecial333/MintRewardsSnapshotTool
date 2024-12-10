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

class TokenSnapshot:
    def __init__(self):
        """Initialize the token snapshot tool using environment variables"""
        load_dotenv()
        
        # Set up logging first
        self.setup_logging()
        
        self.logger.info("Starting TokenSnapshot initialization...")
        
        # Load configuration from .env
        self.rpc_url = os.getenv('SOLANA_RPC_URL')
        self.token_mint = os.getenv('TOKEN_MINT_ADDRESS')
        self.target_mcap = float(os.getenv('TARGET_MCAP_SOL', '500'))
        self.snapshot_dir = os.getenv('SNAPSHOT_DIR', 'snapshots')
        
        # Even more conservative settings
        self.request_delay = 15.0        # Increased to 15 seconds base delay
        self.max_retries = 8
        self.retry_delay = 30            # Increased to 30 seconds base retry delay
        self.jitter_range = 5.0
        self.startup_cooldown = 30.0
        
        # Circuit breaker settings
        self.error_threshold = 3         # Number of errors before circuit breaks
        self.circuit_cooldown = 300.0    # 5 minutes cooldown when circuit breaks
        self.error_window = 60           # Time window for counting errors (seconds)
        self.error_timestamps = []       # Track error timestamps
        self.circuit_broken = False
        self.circuit_break_time = None
        
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

    def make_rpc_request(self, method: str, params: List[Any], retry_count: int = 0) -> Dict:
        """Make a JSON RPC request with retry logic and rate limiting"""
        current_time = datetime.now()
        
        # Check circuit breaker
        if self.check_circuit_breaker():
            wait_time = (self.circuit_break_time + timedelta(seconds=self.circuit_cooldown) - current_time).total_seconds()
            self.logger.warning(f"Circuit breaker active. Waiting {wait_time:.2f} seconds")
            sleep(wait_time)
        
        self.logger.info(f"Starting RPC request for method: {method}")
        self.logger.info(f"Current settings: delay={self.request_delay}, retry_delay={self.retry_delay}")
        
        # Exponential backoff for consecutive requests
        if self.error_count > 0:
            self.request_delay = min(self.request_delay * 1.5, 60.0)  # Cap at 60 seconds
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
                
                self.logger.error(f"RPC error {error_code}: {error_msg}")
                self.logger.error(f"Total errors so far: {self.error_count}")
                
                if error_code in [-32005, 429] and retry_count < self.max_retries:
                    base_wait_time = self.retry_delay * (3 ** retry_count)  # More aggressive backoff
                    jitter = random.uniform(0, self.jitter_range)
                    wait_time = base_wait_time + jitter
                    self.logger.warning(f"Rate limited. Waiting {wait_time:.2f} seconds before retry {retry_count + 1}/{self.max_retries}")
                    sleep(wait_time)
                    return self.make_rpc_request(method, params, retry_count + 1)
            else:
                self.logger.info("Request successful")
                # Reset error count and delay on success
                self.error_count = 0
                self.request_delay = 15.0
                
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

    def get_token_accounts(self) -> List[Dict]:
        """Query token holders using a combination of methods"""
        print("\nStarting token account collection...")
        try:
            holders = []
            
            # Get largest accounts first
            largest_accounts = self.get_token_largest_accounts()
            print(f"Found {len(largest_accounts)} large accounts to process")
            
            for i, account in enumerate(largest_accounts):
                print(f"\nProcessing account {i+1}/{len(largest_accounts)}")
                account_info = self.get_account_info(account['address'])
                
                if account_info and 'data' in account_info:
                    try:
                        parsed_data = account_info['data']['parsed']['info']
                        balance = int(parsed_data['tokenAmount']['amount'])
                        owner = parsed_data['owner']
                        
                        if balance > 0:
                            print(f"Added holder {owner} with balance {balance}")
                            holders.append({
                                'address': owner,
                                'balance': balance
                            })
                    except (KeyError, TypeError) as e:
                        print(f"Error parsing account data: {str(e)}")
                        continue
            
            print(f"\nFinished collecting {len(holders)} holder accounts")
            return holders
            
        except Exception as e:
            print(f"Error in get_token_accounts: {str(e)}")
            return []

    def get_token_sol_price(self) -> float:
        # Placeholder - implement your specific token pricing logic
        return 0.001  # Example value

    def calculate_market_cap(self, total_supply: int) -> float:
        """Calculate market cap in SOL based on current token supply and price"""
        try:
            token_price_in_sol = self.get_token_sol_price()
            market_cap_in_sol = total_supply * token_price_in_sol
            return market_cap_in_sol
        except Exception as e:
            print(f"Error calculating market cap: {str(e)}")
            return None

    def determine_snapshot_interval(self, current_mcap: float) -> int:
        """Determine snapshot interval based on how close we are to target market cap"""
        if current_mcap is None:
            return 3600  # Default to hourly if we can't calculate market cap
        
        mcap_difference = abs(self.target_mcap - current_mcap)
        
        if mcap_difference <= 10:  # Within 10 SOL
            return 60  # Every minute
        elif mcap_difference <= 50:  # Within 50 SOL
            return 300  # Every 5 minutes
        elif mcap_difference <= 100:  # Within 100 SOL
            return 900  # Every 15 minutes
        else:
            return 3600  # Every hour

    def take_snapshot(self) -> Dict:
        """Take a snapshot of all token holders and their balances"""
        print("\nTaking new snapshot...")
        timestamp = datetime.now()
        holders = self.get_token_accounts()
        
        if not holders:
            print("No holders found in snapshot")
            return None
            
        print("Processing holder data...")
        # Create DataFrame
        df = pd.DataFrame(holders)
        
        # Group by address and sum balances
        df = df.groupby('address')['balance'].sum().reset_index()
        
        # Sort by balance descending
        df = df.sort_values('balance', ascending=False)
        
        # Add timestamp
        df['timestamp'] = timestamp.isoformat()
        
        # Calculate total supply and market cap
        total_supply = df['balance'].sum()
        market_cap = self.calculate_market_cap(total_supply)
        
        print(f"Total supply: {total_supply}")
        print(f"Market cap in SOL: {market_cap}")
        
        # Save snapshot with timestamp
        filename = f"{self.snapshot_dir}/snapshot_{timestamp.strftime('%Y%m%d_%H%M%S')}"
        df.to_csv(f"{filename}.csv", index=False)
        
        snapshot_info = {
            'timestamp': timestamp.isoformat(),
            'total_holders': len(df),
            'total_supply': float(total_supply),
            'market_cap_sol': market_cap,
            'target_reached': market_cap >= self.target_mcap if market_cap else False
        }
        
        with open(f"{filename}_info.json", 'w') as f:
            json.dump(snapshot_info, f, indent=2)
        
        print("Snapshot saved successfully")
        return snapshot_info

    def monitor_market_cap(self):
        """Continuously monitor market cap and take snapshots at appropriate intervals"""
        print(f"Starting market cap monitoring. Target: {self.target_mcap} SOL")
        
        while True:
            try:
                snapshot_info = self.take_snapshot()
                
                if snapshot_info:
                    current_mcap = snapshot_info['market_cap_sol']
                    print(f"\nSnapshot taken at {snapshot_info['timestamp']}")
                    print(f"Current Market Cap: {current_mcap:.2f} SOL")
                    print(f"Total Holders: {snapshot_info['total_holders']}")
                    
                    if snapshot_info['target_reached']:
                        print(f"\n🎯 TARGET MARKET CAP REACHED! 🎯")
                        print("Final snapshot saved. Monitoring stopped.")
                        break
                    
                    # Determine next snapshot interval
                    interval = self.determine_snapshot_interval(current_mcap)
                    print(f"Next snapshot in {interval/60:.1f} minutes")
                    
                    time.sleep(interval)
                else:
                    print("Error taking snapshot. Retrying in 1 hour...")
                    time.sleep(3600)
                    
            except Exception as e:
                print(f"Error in monitoring loop: {str(e)}")
                print(f"Stack trace:", e.__traceback__)
                time.sleep(3600)  # Retry in an hour if there's an error

def main():
    # Create .env file template if it doesn't exist
    if not os.path.exists('.env'):
        with open('.env', 'w') as f:
            f.write("""# Solana Configuration
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
TOKEN_MINT_ADDRESS=your_token_mint_address
TARGET_MCAP_SOL=500
SNAPSHOT_DIR=snapshots
""")
        print("Created .env template file. Please fill in your configuration details.")
        return

    snapshot = TokenSnapshot()
    snapshot.monitor_market_cap()

if __name__ == "__main__":
    main()
