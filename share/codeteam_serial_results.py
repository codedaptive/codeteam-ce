"""serial_results: run a landing's steps one after another (codeteam-land's step_results).

Compile batches run serially: zone-tool check saves one guard file per tree with a fixed temp name, so two checks in
the same tree race. procs is consumed lazily, so each step starts only once the one before it has finished.
"""
from collections.abc import Callable, Iterable


def serial_results(procs: Iterable, finish: Callable[[object], dict], on_result: Callable[[dict], None] | None,
                   stop: Callable[[list], None]) -> list[dict]:
    """finish(proc) for each proc in turn, each result passed to on_result when given; when finish raises (an
    interrupted land), stop([that proc]) and raise again, starting no later step."""
    results = []
    for proc in procs:
        try:
            result = finish(proc)
        except BaseException:
            stop([proc])
            raise
        if on_result is not None:
            on_result(result)
        results.append(result)
    return results
