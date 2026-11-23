// PyWin test: C++ with the standard library.
#include <iostream>
#include <vector>
#include <string>
#include <algorithm>
#include <map>
int main() {
    std::vector<int> v = {5, 3, 9, 1, 7};
    std::sort(v.begin(), v.end());
    std::string s = "C++ en PyWin:";
    for (int x : v) s += " " + std::to_string(x);
    std::cout << s << std::endl;
    std::map<std::string, int> m;
    m["uno"] = 1; m["dos"] = 2;
    for (auto &kv : m) std::cout << kv.first << "=" << kv.second << "\n";
    try { throw std::string("excepcion capturada"); }
    catch (const std::string &e) { std::cout << e << std::endl; }
    return 0;
}
