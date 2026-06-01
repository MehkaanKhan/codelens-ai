#include "Entity.h"
#include "Colors.h"
#include <iostream>

Entity::Entity(const std::string& name, int health, int mana)
    : name(name), health(health), mana(mana) {}

std::string Entity::describe() const {
    return name + " [HP:" + std::to_string(health) + " MP:" + std::to_string(mana) + "]";
}

void Entity::takeDamage(int amount) {
    health -= amount;
    if (health < 0) health = 0;
    std::cout << COLOR_RED << name << " takes " << amount << " damage!" << COLOR_RESET << "\n";
}
