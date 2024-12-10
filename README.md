Free for anyone who owns a Solana token to use. I recommend you grab a bag of MintRewards (RWRD) though ... :) ca: 7yM17krfficCdkqg1CNRdptepryrxxFC4hayNmfVuRVc

# Solana Token Snapshot Tool

A Python tool to monitor and capture token holder snapshots for Solana SPL tokens. The tool continuously monitors the token's market cap and adjusts snapshot frequency based on how close it is to a target value.

## Features

- Captures snapshots of token holders and their balances
- Monitors market cap and automatically adjusts snapshot frequency
- Saves snapshots in both CSV and JSON formats
- Implements rate limiting and retry logic for RPC calls
- Supports custom RPC endpoints
- Adapts snapshot frequency based on proximity to target market cap

## Prerequisites

- Python 3.10 or higher
- pip (Python package installer)

## Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd <repository-directory>
   ```

2. Install required dependencies:
   ```bash
   pip install pandas python-dotenv requests base58
   ```

## Configuration

Create a `.env` file in the project root directory with the following parameters:

```ini
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
TOKEN_MINT_ADDRESS=your_token_mint_address
TARGET_MCAP_SOL=500
SNAPSHOT_DIR=snapshots
```

### Parameters:
- `SOLANA_RPC_URL`: Your Solana RPC endpoint (public or private)
- `TOKEN_MINT_ADDRESS`: The mint address of your SPL token
- `TARGET_MCAP_SOL`: Target market cap in SOL where you want to capture the final snapshot
- `SNAPSHOT_DIR`: Directory where snapshots will be saved

## Usage

Run the script:
```bash
python token_snapshot.py
```

The script will:
1. Start monitoring the token's market cap
2. Take periodic snapshots based on proximity to target:
   - Within 10 SOL: Every minute
   - Within 50 SOL: Every 5 minutes
   - Within 100 SOL: Every 15 minutes
   - Otherwise: Every hour
3. Save snapshots to the configured directory
4. Stop when the target market cap is reached

## Output Files

Each snapshot generates two files:

1. CSV file (`snapshot_YYYYMMDD_HHMMSS.csv`) containing:
   - Holder addresses
   - Token balances
   - Timestamp

2. JSON file (`snapshot_YYYYMMDD_HHMMSS_info.json`) containing:
   - Timestamp
   - Total holders
   - Total supply
   - Market cap in SOL
   - Target reached status

## Rate Limiting

The tool implements rate limiting to work with public RPC endpoints:
- 1 second delay between requests
- Maximum 3 retries for failed requests
- Exponential backoff for retries

## Recommendations

### RPC Providers
For better reliability, use a dedicated RPC endpoint provider like:
- QuickNode
- Triton
- Helius
- GenesysGo

### Rate Limit Adjustment
Adjust rate limiting parameters in the code:
```python
self.request_delay = 1.0  # Delay between requests in seconds
self.max_retries = 3     # Maximum number of retries
self.retry_delay = 2     # Base delay for retry backoff
```

## Error Handling

The script includes comprehensive error handling and logging:
- Detailed error messages for RPC calls
- Retry logic for failed requests
- Hourly retries for major failures
- Verbose logging of all operations

## Contributing

Feel free to submit issues and pull requests for additional features or improvements.

## License

Free for anyone who owns a Solana token to use. I recommend you grab a bag of MintRewards (RWRD) though ... :) ca: 7yM17krfficCdkqg1CNRdptepryrxxFC4hayNmfVuRVc
