"""Mini gestionale per biblioteca."""

class Book:
    def __init__(self, title: str, author: str, isbn: str):
        self.title = title
        self.author = author
        self.isbn = isbn
        self.available = True

    def __str__(self):
        status = "Disponibile" if self.available else "Prestato"
        return f"{self.title} di {self.author} [{status}]"

class Library:
    def __init__(self):
        self.books = []

    def add_book(self, book: Book):
        self.books.append(book)

    def search(self, query: str) -> list[Book]:
        return [b for b in self.books if query.lower() in b.title.lower()]

    def lend(self, isbn: str) -> bool:
        for b in self.books:
            if b.isbn == isbn and b.available:
                b.available = False
                return True
        return False

    def return_book(self, isbn: str) -> bool:
        for b in self.books:
            if b.isbn == isbn and not b.available:
                b.available = True
                return True
        return False

def main():
    lib = Library()
    lib.add_book(Book("Il Nome della Rosa", "Umberto Eco", "978-88"))
    lib.add_book(Book("La Divina Commedia", "Dante Alighieri", "978-99"))
    print("Biblioteca inizializzata con", len(lib.books), "libri")

if __name__ == "__main__":
    main()
