def test_compiled_include():
    from pxiprobe import compute

    assert compute(2) == 12
