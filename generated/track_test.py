def track(value, history=None):
    if history is None:
        history = []
    history.append(value)
    return history

if __name__ == "__main__":
    h1 = track(1)
    assert h1 == [1], f"Expected [1], got {h1}"
    
    h2 = track(2, h1)
    assert h2 == [1, 2], f"Expected [1, 2], got {h2}"
    
    track(3, h2)
    assert h2 == [1, 2, 3], f"Expected [1, 2, 3], got {h2}"
    
    print("All tracking tests passed.")
