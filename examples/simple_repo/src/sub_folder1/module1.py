class Module1(object):
    def add(self, a, b):
        a = a + 1
        return a + b + self.helper(a)

    def helper(self, x):
        return x * 2
