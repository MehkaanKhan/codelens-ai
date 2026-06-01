#pragma once
#include "Entity.h"
#include <string>

class Player : public Entity {
private:
    int score;
    int level;

public:
    Player(const std::string& name);

    void attack(Entity& target) override;
    void heal(int amount);
    void gainScore(int points);
    std::string describe() const override;

    int getScore() const { return score; }
    int getLevel() const { return level; }
};
