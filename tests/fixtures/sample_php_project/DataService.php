<?php

namespace App\Services;

use App\Models\User;
use App\Contracts\Processable;

class DataService extends BaseService implements Processable
{
    const VERSION = "1.0";

    private string $name;
    protected int $count = 0;

    public function __construct(string $name)
    {
        $this->name = $name;
    }

    public function process(array $data): array
    {
        if (empty($data)) {
            return [];
        }
        foreach ($data as $item) {
            $this->transform($item);
        }
        return $data;
    }

    public function validate($data): bool
    {
        if (!is_array($data)) {
            return false;
        }
        return count($data) > 0;
    }

    private function transform($item): void
    {
        echo $item;
    }

    public static function create(string $name): self
    {
        return new self($name);
    }
}

interface Processable
{
    public function process(array $data): array;
}

trait Loggable
{
    public function log(string $msg): void
    {
        echo $msg;
    }
}

function standalone_helper(int $x, int $y): int
{
    return $x + $y;
}
