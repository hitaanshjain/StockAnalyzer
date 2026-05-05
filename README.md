# Final Project

This project is a stock screening and analysis application built for our software engineering final project. The system screens U.S. stocks using market momentum and insider-buying activity, builds research packages for selected tickers, and then runs an AI-based analyst workflow to generate writeups for the strongest names.

The project has three main parts:

- `pipeline/stocks.py` builds the stock universe, refreshes market data, runs the screening logic, and creates chart and research outputs.
- `pipeline/agent_workflow.py` takes selected ranked stocks and sends their research packages to the OpenAI API for analyst-style summaries.
- `pipeline/run_pipeline.py` is a wrapper that runs the full workflow from screening through analysis.

The repository also includes a Flask web app that lets users register, log in, choose screener rank ranges, launch analysis jobs, and view results in the browser.

## How to Run the Project

1. Clone the repository and move into the project folder.
2. Create and activate a virtual environment.
3. Install the required dependencies.
4. Create a `.env` file with your API credentials.
5. Run either the pipeline scripts or the Flask app.

Example setup:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file with at least:

```bash
OPENAI_API_KEY=your_key_here
```

Optional variables:

```bash
OPENAI_MODEL=gpt-5.4-mini
OPENAI_WEB_TOOL_TYPE=web_search_preview
SEC_USER_AGENT=YourName your_email@example.com
MONGODB_URI=your_mongodb_uri
MONGODB_DB_NAME=stocks_app
```

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
python app.py
```

## Output

The project generates screening results, chart files, ticker research packages, and AI-written stock reports. These generated folders are ignored by git:

- `data/`
- `screening_output/`
- `agents_data_package/`
- `output/`

## Github

[Github Link](https://github.com/swe-students-spring2026/4-containers-fantastic_five)

## Developers

[Blake Chang](https://github.com/louisvcarpet)
[Peter Ma](https://github.com/pjm9792-ui)
[Tao Xie](https://github.com/tx715)
[Sarya Sadi](https://github.com/saryassadi)
[Hitaansh Jain](https://github.com/hitaanshjain)