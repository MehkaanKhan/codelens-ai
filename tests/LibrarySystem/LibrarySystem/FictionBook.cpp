#include "FictionBook.h"
#include <iostream>
using namespace std;

FictionBook::FictionBook(string t, string a, string i, string g)
    : Book(t, a, i) {
    genre = g;
}

void FictionBook::display() {
    cout << Color::CYAN << "\n[Fiction Book]\n" << Color::RESET;
    cout << " Title   : " << title << "\n";
    cout << " Author  : " << author << "\n";
    cout << " ISBN    : " << isbn << "\n";
    cout << " Genre   : " << genre << "\n";
    cout << " Status  : " << (available ? Color::GREEN + "Available" : Color::RED + "Checked Out") << Color::RESET << "\n";
}

string FictionBook::getGenre() { return genre; }
