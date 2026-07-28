def add(a, b):
    return a + b

if __name__ == "__main__":
    result = add(2, 3)
    print(f"The sum of 2 and 3 is {result}")
    assert result == 5
    print("Verification successful.")
