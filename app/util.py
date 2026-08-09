import threading


def call_with_hard_timeout(fn, timeout: float):
    """Run fn() on a daemon thread and enforce a real wall-clock deadline.

    Together AI requests can hang well past the SDK's own `timeout=` setting
    (observed: a connection the server half-closes without ever completing
    the response, which the underlying HTTP client's read-timeout didn't
    catch). This is a backstop so a single hung call can't strand a page in
    'processing'/'generating' forever — the leaked thread is a daemon, so it
    can't block process shutdown either.
    """
    result: dict = {}

    def runner() -> None:
        try:
            result["value"] = fn()
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    if thread.is_alive():
        raise TimeoutError(f"call did not complete within {timeout}s")
    if "error" in result:
        raise result["error"]
    return result["value"]
