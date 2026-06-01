#pragma once
#include <string>

class Entity {
public:
    std::string name;
    int health;
    int mana;

    Entity(const std::string& name, int health, int mana);
    virtual ~Entity() = default;

    virtual void attack(Entity& target) = 0;
    virtual std::string describe() const;

    bool isAlive() const { return health > 0; }
    void takeDamage(int amount);
};
