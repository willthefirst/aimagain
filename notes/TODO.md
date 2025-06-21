- finish CI/CD work with docker deploys.
  - the double /app directory is confusing, get rid of that
  - simplify simplify simplify
    - add for proposals from llm
  - determine a suitable CI approach given that it would be good to test out built images before merging to main? or at least confirm that images that are on main are runnable , some kind of 'this image passes tests' when on main.
    - need to bring back tests step as well for ci
- update readme to explain local dev setup since we're going to run it with docker now.
  x
