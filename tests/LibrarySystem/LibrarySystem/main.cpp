#include <iostream>
#include <string>
#include "Library.h"
#include "FictionBook.h"
#include "ReferenceBook.h"
#include "Colors.h"
using namespace std;

void printMenu() {
    cout << Color::YELLOW << "\n============================\n";
    cout << "     LIBRARY SYSTEM\n";
    cout << "============================\n" << Color::RESET;
    cout << " [1] List All Books\n";
    cout << " [2] Search by Title\n";
    cout << " [3] Search by Author\n";
    cout << " [4] Checkout Book\n";
    cout << " [5] Return Book\n";
    cout << " [6] Register Member\n";
    cout << " [7] List All Members\n";
    cout << " [8] Member History\n";
    cout << " [9] Library Stats\n";
    cout << " [0] Exit\n";
    cout << "----------------------------\n";
    cout << "Choice: ";
}

int main() {
    Library lib;

    int choice;
    string input1, input2;

    while (true) {
        printMenu();
        cin >> choice;
        cin.ignore();

        if (choice == 1) {
            lib.listAllBooks();

        } else if (choice == 2) {
            cout << "Enter title keyword: ";
            getline(cin, input1);
            lib.searchByTitle(input1);

        } else if (choice == 3) {
            cout << "Enter author keyword: ";
            getline(cin, input1);
            lib.searchByAuthor(input1);

        } else if (choice == 4) {
            cout << "Enter Member ID: ";
            getline(cin, input1);
            cout << "Enter ISBN: ";
            getline(cin, input2);
            lib.checkoutBook(input1, input2);

        } else if (choice == 5) {
            cout << "Enter Member ID: ";
            getline(cin, input1);
            cout << "Enter ISBN: ";
            getline(cin, input2);
            lib.returnBook(input1, input2);

        } else if (choice == 6) {
            cout << "Enter name: ";
            getline(cin, input1);
            cout << "Enter email: ";
            getline(cin, input2);
            lib.addMember(input1, input2);

        } else if (choice == 7) {
            lib.listAllMembers();

        } else if (choice == 8) {
            cout << "Enter Member ID: ";
            getline(cin, input1);
            lib.showMemberHistory(input1);

        } else if (choice == 9) {
            lib.showStats();

        } else if (choice == 0) {
            cout << Color::YELLOW << "\nGoodbye!\n" << Color::RESET;
            break;

        } else {
            cout << Color::RED << "[!] Invalid option.\n" << Color::RESET;
        }
    }

    return 0;
}
