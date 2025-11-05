import random


random_numbers = [random.randint(1, 20) for i in range(10)]

filtered_list_with_comprehension = [random_number for random_number in random_numbers if random_number < 10]

random_numbers_with_filter = list(filter(lambda x: x < 10, random_numbers))

print(random_numbers_with_filter)
print(random_numbers)
print(filtered_list_with_comprehension)