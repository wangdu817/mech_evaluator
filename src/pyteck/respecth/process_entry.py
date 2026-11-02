"""Small importable worker entry point, independent of UI hot reloads."""


def execute_case(case, output, cancel_file):
    from pyteck.respecth.solvers import simulate_case
    import gc
    try:
        from pyteck.respecth.compact_storage import retain_plot_result
        return retain_plot_result(simulate_case(case, output, cancel_file))
    finally:
        gc.collect()
