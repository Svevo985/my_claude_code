def divide(a, b):
    return a / b  # BUG: no divisione per zero check

def main():
    a = float(input("Primo numero: "))
    b = float(input("Secondo numero: "))
    print(f"Risultato: {divide(a, b)}")

if __name__ == "__main__":
    main()
