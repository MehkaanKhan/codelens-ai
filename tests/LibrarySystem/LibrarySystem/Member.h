#ifndef MEMBER_H
#define MEMBER_H
#include <string>
#include <vector>
#include "Colors.h"
using namespace std;

class Member {
private:
    string memberId;
    string name;
    string email;
    int    borrowCount;
    vector<string> borrowedIsbns;

public:
    Member(string id, string n, string e);
    void   display();
    bool   canBorrow();
    void   borrowBook(string isbn);
    void   returnBook(string isbn);
    bool   hasBorrowed(string isbn);
    string getMemberId();
    string getName();
    string getEmail();
    int    getBorrowCount();
    vector<string> getBorrowedIsbns();
};

#endif
