import json

with open("scratch/redux_state.json") as f:
    state = json.load(f)

listingV2 = state.get("listingV2", {})
card_list = listingV2.get("card_list", [])

print("Number of cards:", len(card_list))
if card_list:
    first_card = card_list[0]
    print("Keys of first card:", list(first_card.keys()))
    
    # Save the first card to a file to inspect it
    with open("scratch/first_card.json", "w") as f:
        json.dump(first_card, f, indent=2)
    print("Saved first card details to scratch/first_card.json")
    
    # Check if there is relation to hospitals, or details about the hospital
    # Let's inspect some values
    print("First card type:", first_card.get("type"))
    print("First card name:", first_card.get("name") or first_card.get("title"))
    relations = first_card.get("relations", [])
    print("Relations len:", len(relations))
    if relations:
        print("First relation keys:", list(relations[0].keys()))
        with open("scratch/first_relation.json", "w") as f:
            json.dump(relations[0], f, indent=2)
        print("Saved first relation to scratch/first_relation.json")
