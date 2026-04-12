import threading


def multiply(value):
    result = value * 2
    return result


def process(values):
    output = []
    for value in values:
        output.append(multiply(value))
    return output


def worker(data):
    process(data)


if __name__ == "__main__":
    thread = threading.Thread(target=worker, args=([1, 2, 3],), name="CLI-Worker")
    thread.start()
    thread.join()
