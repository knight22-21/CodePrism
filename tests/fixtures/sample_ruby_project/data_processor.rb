require 'json'
require_relative './helpers'

module Processing

  BATCH_SIZE = 100

  class DataProcessor < BaseProcessor
    include Comparable

    STATUS_CODES = { ok: 0, error: 1 }

    def initialize(config)
      @config = config
      @results = []
    end

    def process(data)
      if data.nil?
        return nil
      elsif data.empty?
        []
      else
        data.map { |item| transform(item) }
      end
    end

    def validate(data)
      return false unless data.is_a?(Array)
      data.all? { |item| item.is_a?(Hash) }
    end

    def self.create(config)
      new(config)
    end

    private

    def transform(item)
      item.to_s.upcase
    end

    def log(msg)
      puts msg
    end
  end

  module Helpers
    def format_output(data)
      data.to_json
    end
  end

end

def standalone_util(x, y)
  x + y
end
