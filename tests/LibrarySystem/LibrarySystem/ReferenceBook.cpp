#include "ReferenceBook.h"
#include <iostream>
using namespace std;

ReferenceBook::ReferenceBook(string t, string a, string i, string s, int ed)
    : Book(t, a, i) {
    subject = s;
    edition = ed;
}

void ReferenceBook::display() {
    cout << Color::YELLOW << "\n[Reference Book]\n" << Color::RESET;
    cout << " Title   : " << title << "\n";
    cout << " Author  : " << author << "\n";
    cout << " ISBN    : " << isbn << "\n";
    cout << " Subject : " << subject << "\n";
    cout << " Edition : " << edition << "\n";
    cout << " Status  : " << (available ? Color::GREEN + "Available" : Color::RED + "Checked Out") << Color::RESET << "\n";
}

string ReferenceBook::getSubject() { return subject; }
int    ReferenceBook::getEdition() { return edition; }
