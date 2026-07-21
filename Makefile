.PHONY: install install-llm data test lint gate eval eval-llm eval-openrouter demo clean

install:            ## Core + dev (no LLM SDKs, no API key)
	pip install -e ".[dev]"

install-llm:        ## Everything: both agent SDKs + OpenRouter backend
	pip install -e ".[dev,sdk,graph,openrouter]"

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

eval-llm:           ## Score both LLM arms, thinking on/off (auto provider)
	python -m evals.run_eval --arm sdk --arm graph --thinking both --dataset holdout

eval-openrouter:    ## Score both LLM arms via OpenRouter (needs OPENROUTER_API_KEY)
	python -m evals.run_eval --arm sdk --arm graph --thinking both --dataset holdout --provider openrouter

demo:               ## Render the terminal demo GIF
	python scripts/make_demo_gif.py

clean:
	rm -rf .pytest_cache .ruff_cache **/__pycache__ *.egg-info
