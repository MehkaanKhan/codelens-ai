#ifndef LIBRARY_H
#define LIBRARY_H
#include <string>
#include <vector>
#include "Book.h"
#include "Member.h"
#include "Colors.h"
using namespace std;

class Library {
private:
    vector<Book*>   books;
    vector<Member*> members;
    int             nextMemberId;

    Book*   findBook(string isbn);
    Member* findMember(string memberId);
    void    saveData();
    void    loadData();

public:
    Library();
    ~Library();

    void addBook(Book* book);
    void addMember(string name, string email);
    void checkoutBook(string memberId, string isbn);
    void returnBook(string memberId, string isbn);
    void searchByTitle(string keyword);
    void searchByAuthor(string keyword);
    void listAllBooks();
    void listAllMembers();
    void showMemberHistory(string memberId);
    void showStats();
};

#endif
