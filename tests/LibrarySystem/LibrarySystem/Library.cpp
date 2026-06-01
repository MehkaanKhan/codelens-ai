#include "Library.h"
#include "FictionBook.h"
#include "ReferenceBook.h"
#include <iostream>
#include <fstream>
#include <sstream>
using namespace std;

Library::Library() {
    nextMemberId = 1;
    loadData();
}

Library::~Library() {
    saveData();
    for (int i = 0; i < books.size(); i++)   delete books[i];
    for (int i = 0; i < members.size(); i++) delete members[i];
}

Book* Library::findBook(string isbn) {
    for (int i = 0; i < books.size(); i++) {
        if (books[i]->getIsbn() == isbn) return books[i];
    }
    return nullptr;
}

Member* Library::findMember(string memberId) {
    for (int i = 0; i < members.size(); i++) {
        if (members[i]->getMemberId() == memberId) return members[i];
    }
    return nullptr;
}

void Library::saveData() {
    // Save members
    ofstream fout("members.txt");
    for (int i = 0; i < members.size(); i++) {
        fout << members[i]->getMemberId() << "|"
             << members[i]->getName()     << "|"
             << members[i]->getEmail()    << "\n";
    }
    fout.close();

    // Save borrow records
    ofstream bout("borrows.txt");
    for (int i = 0; i < members.size(); i++) {
        vector<string> isbns = members[i]->getBorrowedIsbns();
        for (int j = 0; j < isbns.size(); j++) {
            bout << members[i]->getMemberId() << "|" << isbns[j] << "\n";
        }
    }
    bout.close();
}

void Library::loadData() {
    // Load members
    ifstream fin("members.txt");
    if (fin) {
        string line;
        while (getline(fin, line)) {
            stringstream ss(line);
            string id, name, email;
            getline(ss, id,    '|');
            getline(ss, name,  '|');
            getline(ss, email, '|');
            members.push_back(new Member(id, name, email));
            int num = stoi(id.substr(1));
            if (num >= nextMemberId) nextMemberId = num + 1;
        }
        fin.close();
    }

    // Load borrow records
    ifstream bin("borrows.txt");
    if (bin) {
        string line;
        while (getline(bin, line)) {
            stringstream ss(line);
            string memberId, isbn;
            getline(ss, memberId, '|');
            getline(ss, isbn,     '|');
            Member* m = findMember(memberId);
            if (m) m->borrowBook(isbn);
        }
        bin.close();
    }

    // Seed default books if none saved
    if (books.empty()) {
        books.push_back(new FictionBook("The Great Gatsby",    "F. Scott Fitzgerald", "978-0743273565", "Classic"));
        books.push_back(new FictionBook("1984",                "George Orwell",        "978-0451524935", "Dystopian"));
        books.push_back(new FictionBook("To Kill a Mockingbird","Harper Lee",          "978-0061935466", "Drama"));
        books.push_back(new ReferenceBook("Clean Code",        "Robert C. Martin",    "978-0132350884", "Software",  1));
        books.push_back(new ReferenceBook("The Pragmatic Programmer","David Thomas",   "978-0135957059", "Software",  2));
        books.push_back(new ReferenceBook("Data Structures",   "Mark Weiss",          "978-0132576277", "Computer Science", 3));
    }

    // Sync book availability from borrow records
    ifstream bin2("borrows.txt");
    if (bin2) {
        string line;
        while (getline(bin2, line)) {
            stringstream ss(line);
            string memberId, isbn;
            getline(ss, memberId, '|');
            getline(ss, isbn,     '|');
            Book* b = findBook(isbn);
            if (b) b->setAvailable(false);
        }
        bin2.close();
    }
}

void Library::addBook(Book* book) {
    books.push_back(book);
    cout << Color::GREEN << "[+] Book added: " << book->getTitle() << Color::RESET << "\n";
}

void Library::addMember(string name, string email) {
    string id = "M" + to_string(nextMemberId++);
    members.push_back(new Member(id, name, email));
    cout << Color::GREEN << "[+] Member registered. ID: " << id << Color::RESET << "\n";
}

void Library::checkoutBook(string memberId, string isbn) {
    Member* m = findMember(memberId);
    if (!m) {
        cout << Color::RED << "[!] Member not found.\n" << Color::RESET;
        return;
    }
    Book* b = findBook(isbn);
    if (!b) {
        cout << Color::RED << "[!] Book not found.\n" << Color::RESET;
        return;
    }
    if (!b->isAvailable()) {
        cout << Color::RED << "[!] Book is already checked out.\n" << Color::RESET;
        return;
    }
    if (!m->canBorrow()) {
        cout << Color::RED << "[!] Member has reached borrow limit (3 books).\n" << Color::RESET;
        return;
    }
    b->setAvailable(false);
    m->borrowBook(isbn);
    cout << Color::GREEN << "[+] Checked out \"" << b->getTitle() << "\" to " << m->getName() << ".\n" << Color::RESET;
}

void Library::returnBook(string memberId, string isbn) {
    Member* m = findMember(memberId);
    if (!m) {
        cout << Color::RED << "[!] Member not found.\n" << Color::RESET;
        return;
    }
    if (!m->hasBorrowed(isbn)) {
        cout << Color::RED << "[!] This member did not borrow that book.\n" << Color::RESET;
        return;
    }
    Book* b = findBook(isbn);
    if (b) b->setAvailable(true);
    m->returnBook(isbn);
    cout << Color::GREEN << "[+] Book returned successfully.\n" << Color::RESET;
}

void Library::searchByTitle(string keyword) {
    cout << Color::BOLD << "\n-- Search Results (Title: \"" << keyword << "\") --\n" << Color::RESET;
    bool found = false;
    for (int i = 0; i < books.size(); i++) {
        if (books[i]->getTitle().find(keyword) != string::npos) {
            books[i]->display();
            found = true;
        }
    }
    if (!found) cout << " No books matched.\n";
}

void Library::searchByAuthor(string keyword) {
    cout << Color::BOLD << "\n-- Search Results (Author: \"" << keyword << "\") --\n" << Color::RESET;
    bool found = false;
    for (int i = 0; i < books.size(); i++) {
        if (books[i]->getAuthor().find(keyword) != string::npos) {
            books[i]->display();
            found = true;
        }
    }
    if (!found) cout << " No books matched.\n";
}

void Library::listAllBooks() {
    cout << Color::BOLD << "\n========== ALL BOOKS ==========\n" << Color::RESET;
    if (books.empty()) {
        cout << " No books in library.\n";
        return;
    }
    for (int i = 0; i < books.size(); i++) {
        books[i]->display();
    }
}

void Library::listAllMembers() {
    cout << Color::BOLD << "\n========= ALL MEMBERS =========\n" << Color::RESET;
    if (members.empty()) {
        cout << " No members registered.\n";
        return;
    }
    for (int i = 0; i < members.size(); i++) {
        members[i]->display();
    }
}

void Library::showMemberHistory(string memberId) {
    Member* m = findMember(memberId);
    if (!m) {
        cout << Color::RED << "[!] Member not found.\n" << Color::RESET;
        return;
    }
    m->display();
    vector<string> isbns = m->getBorrowedIsbns();
    if (!isbns.empty()) {
        cout << Color::CYAN << "\n Currently borrowed:\n" << Color::RESET;
        for (int i = 0; i < isbns.size(); i++) {
            Book* b = findBook(isbns[i]);
            if (b) cout << "  - " << b->getTitle() << " (" << isbns[i] << ")\n";
        }
    }
}

void Library::showStats() {
    int totalBooks     = books.size();
    int checkedOut     = 0;
    int totalMembers   = members.size();
    int activeMembers  = 0;

    for (int i = 0; i < books.size(); i++) {
        if (!books[i]->isAvailable()) checkedOut++;
    }
    for (int i = 0; i < members.size(); i++) {
        if (members[i]->getBorrowCount() > 0) activeMembers++;
    }

    cout << Color::BOLD << "\n========= LIBRARY STATS =========\n" << Color::RESET;
    cout << " Total Books    : " << totalBooks                    << "\n";
    cout << " Available      : " << (totalBooks - checkedOut)     << "\n";
    cout << " Checked Out    : " << checkedOut                    << "\n";
    cout << " Total Members  : " << totalMembers                  << "\n";
    cout << " Active Members : " << activeMembers                 << "\n";
    cout << Color::BOLD << "==================================\n" << Color::RESET;
}
