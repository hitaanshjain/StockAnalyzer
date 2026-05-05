# Final Project

![Web CI/CD](https://github.com/swe-students-spring2026/5-final-lakers_in_five/actions/workflows/web.yml/badge.svg)
![Pipeline CI/CD](https://github.com/swe-students-spring2026/5-final-lakers_in_five/actions/workflows/pipeline.yml/badge.svg)
![Mongo Service CI/CD](https://github.com/swe-students-spring2026/5-final-lakers_in_five/actions/workflows/mongo_service.yml/badge.svg)

This project is a stock research platform built for our software engineering final project. It screens U.S. stocks using momentum and insider-buying signals, builds research packages for selected tickers, runs an AI analyst workflow on those packages, and exposes the process through a Flask web app backed by MongoDB.

## Subsystems

The project follows the course requirement that each custom subsystem lives in its own subdirectory:

- `web/`: Flask application, HTML templates, and web tests
- `pipeline/`: stock screener, AI analysis workflow, and pipeline tests
- `mongo_service/`: MongoDB helper code, seed/import tooling, and Mongo tests

## Docker Images

- Web subsystem: `https://hub.docker.com/r/<your-dockerhub-username>/stocks-web`
- Pipeline subsystem: `https://hub.docker.com/r/<your-dockerhub-username>/stocks-pipeline`
- Mongo helper subsystem: `https://hub.docker.com/r/<your-dockerhub-username>/swe-mongo-service`

## What The Project Does

The pipeline starts by building a stock universe and filtering for U.S. common stocks. It refreshes price and metadata caches, scores momentum trends, overlays insider purchase activity, and creates per-ticker research packages with charts and filings. The AI stage then reads those packages and generates structured analyst writeups focused on whether a stock move looks like a real but still incomplete repricing.

The web app allows a user to register, log in, choose a rank range from the screener, launch analysis jobs, poll logs, and read stored results. MongoDB is used to store users, jobs, screening snapshots, analysis sessions, and stock report records.

## Repository Layout

```text
.
├── web/
├── pipeline/
├── mongo_service/
├── docker-compose.yml
├── .env.example
└── README.md
```

## Local Setup

1. Clone the repository.
2. Create and activate a virtual environment.
3. Install the dependencies for all three subsystems.
4. Copy `.env.example` to `.env`.
5. Start MongoDB and run the parts you need.

Example:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r web/requirements.txt
pip install -r pipeline/requirements.txt
pip install -r mongo_service/requirements.txt
pip install pytest pytest-cov
cp .env.example .env
```

## Environment Variables

Put these values in `.env`:

```bash
OPENAI_API_KEY=your_openai_api_key_here
SEC_USER_AGENT=YourName your_email@example.com
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB_NAME=stocks_app
FLASK_SECRET_KEY=your_random_secret_here
```

Optional values:

```bash
OPENAI_MODEL=gpt-5.4-mini
OPENAI_WEB_TOOL_TYPE=web_search_preview
```

## Running The Project

Run the stock screener only:

```bash
python pipeline/stocks.py
```

Run the analyst workflow only:

```bash
python pipeline/agent_workflow.py --start-rank 1 --end-rank 3
```

Run the full pipeline:

```bash
python pipeline/run_pipeline.py --start-rank 1 --end-rank 3
```

Run the web app:

```bash
python web/app.py
```

Run the full Docker stack:

```bash
docker compose up --build
```

Import starter pipeline output into MongoDB after generating output:

```bash
docker compose --profile seed up mongo_seed
```

## Testing

Run all tests:

```bash
pytest mongo_service/tests pipeline/tests web/tests
```

The CI workflows for `web`, `pipeline`, and `mongo_service` each build, test, and publish their own subsystem independently.

## Generated Output

Generated runtime output is not intended to be committed:

- `data/`
- `screening_output/`
- `agents_data_package/`
- `output/`

## Github

[Github Link](https://github.com/swe-students-spring2026/5-final-lakers_in_five)

## Developers

- [Blake Chang](https://github.com/louisvcarpet)
- [Peter Ma](https://github.com/pjm9792-ui)
- [Tao Xie](https://github.com/tx715)
- [Sarya Sadi](https://github.com/saryassadi)
- [Hitaansh Jain](https://github.com/hitaanshjain)
