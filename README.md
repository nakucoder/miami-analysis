# Miami Data Analysis

Jupyter notebook analyzing real-time Miami weather, crypto, and stock market data pulled from AWS S3.

## What it does

- Connects to AWS S3 and loads JSON snapshots saved by the Miami data pipelines
- Analyzes and visualizes trends for weather, crypto, and stocks over time
- Generates charts saved as PNG files

## Charts

- **crypto_analysis.png** — Bitcoin, Ethereum, and Solana price trends
- **stock_analysis.png** — NVDA, AAPL, MSFT, VOO, AMZN price trends
- **weather_analysis.png** — Miami temperature and wind speed trends

## Tech Stack

- Python, Jupyter Notebook
- boto3 — AWS S3 access
- pandas — data manipulation
- matplotlib — charting

## Data Sources

Data is pulled from S3 bucket `miami-weather-pipeline-juan` populated by:
- [weather-pipeline](https://github.com/nakucoder/weather-pipeline)
- [crypto-pipeline](https://github.com/nakucoder/crypto-pipeline)
- [stock-pipeline](https://github.com/nakucoder/stock-pipeline)

## Author

Built by **Juan Spinelli** · FastAPI + Docker + AWS S3
