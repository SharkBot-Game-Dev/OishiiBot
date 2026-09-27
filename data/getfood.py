import time
import requests

ENDPOINT = "https://query.wikidata.org/sparql"

QUERY = """
SELECT DISTINCT ?item ?itemLabel WHERE {
  ?item wdt:P31/wdt:P279* wd:Q2095.

  SERVICE wikibase:label {
    bd:serviceParam wikibase:language "ja".
    ?item rdfs:label ?itemLabel.
  }

  FILTER(LANG(?itemLabel) = "ja")
}
LIMIT %d
OFFSET %d
"""

HEADERS = {
    "User-Agent": "FoodDictionaryBuilder/1.0 (Python requests)"
}


def fetch_foods(limit=1000):
    foods = set()
    offset = 0

    while True:
        print(f"取得中: offset={offset:,}")

        query = QUERY % (limit, offset)

        try:
            response = requests.get(
                ENDPOINT,
                params={
                    "query": query,
                    "format": "json",
                },
                headers=HEADERS,
                timeout=60,
            )

            response.raise_for_status()

        except requests.RequestException as e:
            print("取得失敗:", e)
            print("10秒後に再試行します")
            time.sleep(10)
            continue

        data = response.json()

        rows = data["results"]["bindings"]

        if not rows:
            break

        for row in rows:
            label = row["itemLabel"]["value"].strip()

            if label:
                foods.add(label)

        print(f"現在: {len(foods):,}語")

        if len(rows) < limit:
            break

        offset += limit
        
        time.sleep(1)

    return foods


def save_foods(foods, filename="foods.txt"):
    foods = sorted(foods)

    with open(filename, "w", encoding="utf-8") as f:
        for food in foods:
            f.write(food + "\n")

    print()
    print(f"{filename} に {len(foods):,}語保存しました")


if __name__ == "__main__":
    foods = fetch_foods()
    save_foods(foods)