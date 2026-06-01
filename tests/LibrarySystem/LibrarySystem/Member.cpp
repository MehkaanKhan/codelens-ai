#include "Member.h"
#include <iostream>
using namespace std;

Member::Member(string id, string n, string e) {
    memberId    = id;
    name        = n;
    email       = e;
    borrowCount = 0;
}

void Member::display() {
    cout << Color::MAGENTA << "\n[Member]\n" << Color::RESET;
    cout << " ID       : " << memberId << "\n";
    cout << " Name     : " << name << "\n";
    cout << " Email    : " << email << "\n";
    cout << " Borrowed : " << borrowCount << " book(s)\n";
    if (!borrowedIsbns.empty()) {
        cout << " ISBNs    : ";
        for (int i = 0; i < borrowedIsbns.size(); i++) {
            cout << borrowedIsbns[i];
            if (i < borrowedIsbns.size() - 1) cout << ", ";
        }
        cout << "\n";
    }
}

bool Member::canBorrow() {
    return borrowCount < 3;
}

void Member::borrowBook(string isbn) {
    borrowedIsbns.push_back(isbn);
    borrowCount++;
}

void Member::returnBook(string isbn) {
    for (int i = 0; i < borrowedIsbns.size(); i++) {
        if (borrowedIsbns[i] == isbn) {
            borrowedIsbns.erase(borrowedIsbns.begin() + i);
            borrowCount--;
            return;
        }
    }
}

bool Member::hasBorrowed(string isbn) {
    for (int i = 0; i < borrowedIsbns.size(); i++) {
        if (borrowedIsbns[i] == isbn) return true;
    }
    return false;
}

string Member::getMemberId()  { return memberId; }
string Member::getName()      { return name; }
string Member::getEmail()     { return email; }
int    Member::getBorrowCount(){ return borrowCount; }
vector<string> Member::getBorrowedIsbns() { return borrowedIsbns; }
