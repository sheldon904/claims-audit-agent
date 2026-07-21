.PHONY: install install-llm data test lint gate eval eval-llm demo clean

install:            ## Core + dev (no LLM SDKs, no API key)
	pip install -e ".[dev]"

install-llm:        ## Everything, including both agent SDKs
	pip install -e ".[dev,sdk,graph]"

data:               ## Regenerate the synthetic dataset (deterministic)
	python -m data.generate

test:               ## Run the test suite
	pytest -q

lint:               ## Ruff lint
	ruff check .

gate:               ## The deterministic eval regression gate
	python -m evals.gate

eval:               ## Score the deterministic engine on the holdout
	python -m evals.run_eval --arm engine --dataset holdout

eval-llm:           ## Score both LLM arms, thinking on/off (needs ANTHROPIC_API_KEY)
	python -m evals.run_eval --arm sdk --arm graph --thinking both --dataset holdout

demo:               ## Render the terminal demo GIF
	python scripts/make_demo_gif.py

clean:
	rm -rf .pytest_cache .ruff_cache **/__pycache__ *.egg-info
