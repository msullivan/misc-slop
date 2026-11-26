import random, zoo
class _W:
    cls = None
    def __init__(self): self.b = self.cls(random.Random(7))
    def move(self): return self.b.move()
    def observe(self, o): self.b.observe(o)
def mk(c):
    return type(c.__name__, (_W,), {"cls": c})
TFT = mk(zoo.TFT); Contrite = mk(zoo.ContriteTFT); Gradual = mk(zoo.Gradual); Pavlov = mk(zoo.Pavlov)
