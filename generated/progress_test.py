def progress_percentage(completed, total):
    if total == 0:
        return 0.0
    return round((completed / total) * 100, 2)

if __name__ == "__main__":
    assert progress_percentage(3, 10) == 30.0
    assert progress_percentage(0, 0) == 0.0
    assert progress_percentage(10, 10) == 100.0
    assert progress_percentage(1, 3) == 33.33
    print("All progress tests passed.")
