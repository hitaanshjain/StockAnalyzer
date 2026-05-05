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

## Live App

The app is deployed and running at:

**http://204.48.16.73:5001**

Register an account, then use the dashboard to launch stock screening and analysis jobs.

## Developer Setup

These instructions are for developers who want to run the project locally.

**Prerequisites:** Docker must be installed. Get it at [docs.docker.com/get-docker](https://docs.docker.com/get-docker/).

1. Clone the repository:

```bash
git clone https://github.com/swe-students-spring2026/5-final-lakers_in_five.git
cd 5-final-lakers_in_five
```

2. Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

## Environment Variables

Edit `.env` with your real credentials:

```bash
OPENAI_API_KEY=your_openai_api_key_here
SEC_USER_AGENT=YourName your_email@example.com
MONGODB_URI=mongodb://mongodb:27017
MONGODB_DB_NAME=stocks_app
FLASK_SECRET_KEY=your_random_secret_here
```

See `.env.example` for a full template. `MONGODB_URI` should stay as `mongodb://mongodb:27017` when running with Docker — it points to the MongoDB container.

## Running Locally

**Start the web app and database:**

```bash
docker compose up --build
```

The web app will be available at `http://localhost:5001`.

**Run the stock screener pipeline (opt-in):**

```bash
docker compose --profile pipeline run pipeline
```

**Import pipeline output into MongoDB:**

```bash
docker compose --profile seed up mongo_seed
```

## Testing

```bash
pip install pytest pytest-cov
pytest mongo_service/tests pipeline/tests web/tests
```

The CI workflows for `web`, `pipeline`, and `mongo_service` each build, test, and publish their own Docker image independently on every push to main.

## Live Analysis Note

If an error appears in the live analysis output while a run is in progress, it is usually a scraping or upstream data-fetch issue rather than a problem with the overall web app. In most cases this does not mean the whole system is broken, and it is generally safe to rerun the analysis.

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
