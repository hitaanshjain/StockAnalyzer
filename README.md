# Stock Research Platform

![Web CI/CD](https://github.com/swe-students-spring2026/5-final-lakers_in_five/actions/workflows/web.yml/badge.svg)
![Pipeline CI/CD](https://github.com/swe-students-spring2026/5-final-lakers_in_five/actions/workflows/pipeline.yml/badge.svg)
![Mongo Service CI/CD](https://github.com/swe-students-spring2026/5-final-lakers_in_five/actions/workflows/mongo_service.yml/badge.svg)

A full-stack stock research platform that screens U.S. equities using momentum and insider-buying signals, generates AI-powered analyst writeups, and presents everything through a web dashboard backed by MongoDB.

## What It Does

The platform has two main workflows. First, the **screener pipeline** builds a universe of U.S. common stocks, scores each one using an 8-month momentum model and recent insider purchase activity, and produces a ranked list with charts and SEC filing summaries. Second, the **AI analyst** reads those research packages and writes structured reports that evaluate whether a stock's recent move looks like a real but still-incomplete repricing.

The **web app** ties it together: register an account, pick a rank range from the screener, launch an analysis job, watch the live log output, and read the stored results — all from the browser.

## Subsystems

| Subsystem | Description | Docker Image |
|-----------|-------------|--------------|
| `web/` | Flask app, HTML templates, authentication, job management | [stocks-web on Docker Hub](https://hub.docker.com/r/tx715/stocks-web) |
| `pipeline/` | Stock screener, momentum scoring, insider data, AI analyst workflow | [stocks-pipeline on Docker Hub](https://hub.docker.com/r/tx715/stocks-pipeline) |
| `mongo_service/` | MongoDB helper utilities, data seeding, import tooling | [swe-mongo-service on Docker Hub](https://hub.docker.com/r/tx715/swe-mongo-service) |

## Live App

The app is deployed and running at:

**http://204.48.16.73:5001**

Register an account, then use the dashboard to launch stock screening and analysis jobs.

## Repository Layout

```
.
├── web/                  # Flask web application
├── pipeline/             # Stock screener and AI analyst
├── mongo_service/        # MongoDB helpers and seed tooling
├── docker-compose.yml    # Orchestrates all services
├── .env.example          # Template for required environment variables
└── README.md
```

## Developer Setup

These instructions will get the project running on any machine with Docker installed.

**Prerequisites:** Install Docker from [docs.docker.com/get-docker](https://docs.docker.com/get-docker/).

**1. Clone the repository:**

```bash
git clone https://github.com/swe-students-spring2026/5-final-lakers_in_five.git
cd 5-final-lakers_in_five
```

**2. Create your `.env` file:**

```bash
cp .env.example .env
```

Then open `.env` and fill in your credentials (see the Environment Variables section below).

**3. Start the web app and database:**

```bash
docker compose up --build
```

The web app will be available at **http://localhost:5001**. Register an account and log in to access the dashboard.

**4. (Optional) Run the stock screener pipeline:**

The pipeline is opt-in and runs separately from the web app:

```bash
docker compose --profile pipeline run pipeline
```

This downloads price data, scores stocks, fetches insider activity, and generates research packages. It can take 20–60 minutes depending on your internet connection and machine.

**5. (Optional) Import pipeline output into MongoDB:**

After the pipeline finishes, seed its output into the database so the web app can display results:

```bash
docker compose --profile seed up mongo_seed
```

## Environment Variables

Copy `.env.example` to `.env` and fill in the following values:

```bash
# Required: OpenAI API key for the AI analyst workflow
OPENAI_API_KEY=your_openai_api_key_here

# Required: Identifies your app to the SEC EDGAR API (use your real name and email)
SEC_USER_AGENT=Your Name your_email@example.com

# Required: MongoDB connection string
# Use the value below when running with Docker Compose (points to the mongodb container)
MONGODB_URI=mongodb://mongodb:27017

# The database name — leave this as-is
MONGODB_DB_NAME=stocks_app

# Required: Random secret key for Flask session security (generate any long random string)
FLASK_SECRET_KEY=your_random_secret_here
```

See `.env.example` in the repository for the full template. `MONGODB_URI` should stay as `mongodb://mongodb:27017` when running locally with Docker Compose — it points to the `mongodb` container by its service name.

## Running Tests

Install test dependencies and run all tests across all three subsystems:

```bash
pip install pytest pytest-cov
pytest mongo_service/tests pipeline/tests web/tests --cov=. --cov-report=term-missing
```

Each subsystem's CI workflow enforces at least 80% code coverage.

## CI/CD

Every push or pull request to `main` triggers the GitHub Actions workflows. Each subsystem has its own workflow that independently builds, tests, and pushes its Docker image to Docker Hub. The `web` workflow also deploys the latest image to Digital Ocean automatically.

## Generated Output

The following directories are created at runtime and are not committed to the repository:

- `data/` — price and metadata caches
- `screening_output/` — screener results and charts
- `agents_data_package/` — per-ticker research packages
- `output/` — final pipeline output

## Live Analysis Note

If an error appears in the live output during an analysis run, it is usually a transient scraping or upstream data-fetch issue (Yahoo Finance, OpenInsider, or SEC EDGAR). The overall system is still healthy — it is generally safe to rerun the job.

## GitHub

[github.com/swe-students-spring2026/5-final-lakers_in_five](https://github.com/swe-students-spring2026/5-final-lakers_in_five)

## Developers

- [Blake Chang](https://github.com/louisvcarpet)
- [Peter Ma](https://github.com/pjm9792-ui)
- [Tao Xie](https://github.com/tx715)
- [Sarya Sadi](https://github.com/saryassadi)
- [Hitaansh Jain](https://github.com/hitaanshjain)
