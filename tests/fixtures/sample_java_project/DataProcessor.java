package com.example;

import java.util.List;
import java.util.ArrayList;

public class DataProcessor implements Processable {

    private String name;
    private static final int MAX_SIZE = 100;

    public DataProcessor(String name) {
        this.name = name;
    }

    @Override
    public List<String> process(List<String> items) {
        List<String> result = new ArrayList<>();
        for (String item : items) {
            if (item != null && !item.isEmpty()) {
                result.add(transform(item));
            }
        }
        return result;
    }

    private String transform(String input) {
        if (input.length() > MAX_SIZE) {
            return input.substring(0, MAX_SIZE);
        }
        return input.toUpperCase();
    }

    public String getName() {
        return name;
    }
}

interface Processable {
    List<String> process(List<String> items);
}
