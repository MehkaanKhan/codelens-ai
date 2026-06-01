#include "Book.h"
using namespace std;

Book::Book(string t, string a, string i) {
    title     = t;
    author    = a;
    isbn      = i;
    available = true;
}

string Book::getTitle()   { return title; }
string Book::getAuthor()  { return author; }
string Book::getIsbn()    { return isbn; }
bool   Book::isAvailable(){ return available; }

void Book::setAvailable(bool status) {
    available = status;
}
