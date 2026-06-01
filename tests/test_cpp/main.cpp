#include <iostream>
#include <fstream>
#include <string>
#include <stdexcept>
#include "Player.h"
#include "Colors.h"

void saveGame(const Player& player, const std::string& filename) {
    std::ofstream f(filename);
    if (!f) throw std::runtime_error("Cannot open file: " + filename);
    f << player.getScore() << "\n" << player.getLevel() << "\n";
}

int loadScore(const std::string& filename) {
    std::ifstream f(filename);
    if (!f) {
        // file not found: return 0 as default
        return 0;
    }
    int score = 0;
    f >> score;
    return score;
}

int main() {
    std::cout << COLOR_YELLOW << "=== Dungeon Quest ===" << COLOR_RESET << "\n";

    std::cout << "Enter your name: ";
    std::string name;
    std::getline(std::cin, name);
    if (name.empty()) name = "Hero";

    Player player(name);
    std::cout << player.describe() << "\n";

    int choice = 0;
    while (player.isAlive() && choice != 3) {
        std::cout << "\n1) Attack  2) Heal  3) Quit\n> ";
        std::cin >> choice;

        if (choice == 1) {
            player.gainScore(10);
        } else if (choice == 2) {
            player.heal(20);
        }
    }

    saveGame(player, "save.txt");
    int prev = loadScore("save.txt");
    std::cout << COLOR_YELLOW << "Final score: " << prev << COLOR_RESET << "\n";
    return 0;
}
