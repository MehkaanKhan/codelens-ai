#ifndef REFERENCEBOOK_H
#define REFERENCEBOOK_H
#include "Book.h"
#include <string>
using namespace std;

class ReferenceBook : public Book {
private:
    string subject;
    int    edition;

public:
    ReferenceBook(string t, string a, string i, string s, int ed);
    void display() override;
    string getSubject();
    int    getEdition();
};

#endif
