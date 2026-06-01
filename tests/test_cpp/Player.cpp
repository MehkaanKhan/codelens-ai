#include "Player.h"
#include "Colors.h"
#include <iostream>
#include <stdexcept>

Player::Player(const std::string& name)
    : Entity(name, MAX_HEALTH, MAX_MANA), score(0), level(1) {}

void Player::attack(Entity& target) {
    int damage = 10 + level * 2;
    std::cout << COLOR_GREEN << name << " attacks " << target.name
              << " for " << damage << " damage!" << COLOR_RESET << "\n";
    target.takeDamage(damage);
}

void Player::heal(int amount) {
    int actual = (health + amount > MAX_HEALTH) ? MAX_HEALTH - health : amount;
    health += actual;
    std::cout << COLOR_GREEN << name << " heals " << actual << " HP." << COLOR_RESET << "\n";
}

void Player::gainScore(int points) {
    score += points;
    if (score >= level * 100) {
        level++;
        std::cout << COLOR_YELLOW << name << " leveled up to " << level << "!" << COLOR_RESET << "\n";
    }
}

std::string Player::describe() const {
    return Entity::describe() + " Score:" + std::to_string(score) + " Lvl:" + std::to_string(level);
}
