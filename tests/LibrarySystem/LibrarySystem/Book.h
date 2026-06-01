#ifndef BOOK_H
#define BOOK_H
#include <string>
#include "Colors.h"
using namespace std;

class Book {
protected:
    string title;
    string author;
    string isbn;
    bool available;

public:
    Book(string t, string a, string i);
    virtual void display() = 0;
    string getTitle();
    string getAuthor();
    string getIsbn();
    bool isAvailable();
    void setAvailable(bool status);
};

#endif
