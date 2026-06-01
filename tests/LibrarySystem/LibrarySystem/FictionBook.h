#ifndef FICTIONBOOK_H
#define FICTIONBOOK_H
#include "Book.h"
#include <string>
using namespace std;

class FictionBook : public Book {
private:
    string genre;

public:
    FictionBook(string t, string a, string i, string g);
    void display() override;
    string getGenre();
};

#endif
