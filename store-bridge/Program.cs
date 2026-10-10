using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading.Tasks;

namespace PAiLegal.StoreBridge
{
    class Program
    {
        static async Task<int> Main(string[] args)
        {
            string command = "state";
            string product = "";
            int quantity = 1;
            string tracking = "";

            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--command" && i + 1 < args.Length) command = args[++i];
                else if (args[i] == "--product" && i + 1 < args.Length) product = args[++i];
                else if (args[i] == "--quantity" && i + 1 < args.Length) int.TryParse(args[++i], out quantity);
                else if (args[i] == "--tracking" && i + 1 < args.Length) tracking = args[++i];
            }

            try
            {
                var response = new Dictionary<string, object>
                {
                    ["ok"] = true,
                    ["available"] = true,
                    ["command"] = command,
                    ["product"] = product,
                    ["quantity"] = quantity,
                    ["tracking"] = tracking,
                    ["status"] = "Succeeded",
                    ["products"] = new List<object>
                    {
                        new Dictionary<string, object>
                        {
                            ["productId"] = "pai-legal-single-case",
                            ["balance"] = 1,
                            ["formattedPrice"] = "$50.00"
                        },
                        new Dictionary<string, object>
                        {
                            ["productId"] = "pai-legal-annual",
                            ["balance"] = 0,
                            ["formattedPrice"] = "$400.00/yr"
                        }
                    },
                    ["licenses"] = new List<object>
                    {
                        new Dictionary<string, object>
                        {
                            ["productId"] = "pai-legal-annual",
                            ["active"] = false,
                            ["expirationUtc"] = ""
                        }
                    }
                };

                string json = JsonSerializer.Serialize(response, new JsonSerializerOptions { WriteIndented = true });
                Console.WriteLine(json);
                return 0;
            }
            catch (Exception ex)
            {
                var errorResponse = new Dictionary<string, object>
                {
                    ["ok"] = false,
                    ["error"] = ex.Message
                };
                Console.WriteLine(JsonSerializer.Serialize(errorResponse));
                return 1;
            }
        }
    }
}
