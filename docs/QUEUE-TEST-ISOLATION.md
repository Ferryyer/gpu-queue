# Queue unit tests

The suite requires `~/scratch` to exist because its fixtures create temporary directories there. From the repository root, prepare that directory before running the queue baseline:

```sh
mkdir -p "$HOME/scratch"
python3 -m unittest discover -s tests -p test_gpuqueue.py
```

The suite uses temporary queue state under `~/scratch` and mocked platform responses to cover local queue behavior.
