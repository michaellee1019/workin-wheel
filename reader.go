package main

import (
    "context"
    "encoding/json"
    "fmt"
    "io/ioutil"
    "log"
    "math"
    "os"
    "time"

    "github.com/spf13/pflag"
    "golang.org/x/oauth2"
    "golang.org/x/oauth2/google"
    "google.golang.org/api/calendar/v3"
    "google.golang.org/api/option"
    viam "go.viam.com/rdk/components/motor"
	"go.viam.com/rdk/robot/client"
    "go.viam.com/utils/rpc"
	"go.viam.com/rdk/logging"
	"go.viam.com/rdk/components/motor"
)

const (
    SCOPES            = "https://www.googleapis.com/auth/calendar.readonly"
    TOKEN_FILE        = "token.json"
    CREDENTIALS_FILE  = "credentials.json"
    OUT_OF_OFFICE     = 0
    WORK_FROM_HOME    = 1
    GOING_TO_EVENT    = 2
    FOCUS_TIME        = 3
    AVAILABLE         = 4
    IN_MEETING        = 5
)

var eventTypeToWheelPosition = map[string]int{
    "outOfOffice": OUT_OF_OFFICE,
    "focusTime":   FOCUS_TIME,
    "default":     IN_MEETING,
}

func getCreds() (*oauth2.Config, *oauth2.Token, error) {
    b, err := ioutil.ReadFile(CREDENTIALS_FILE)
    if err != nil {
        return nil, nil, fmt.Errorf("unable to read client secret file: %v", err)
    }

    config, err := google.ConfigFromJSON(b, SCOPES)
    if err != nil {
        return nil, nil, fmt.Errorf("unable to parse client secret file to config: %v", err)
    }

    tokFile := TOKEN_FILE
    tok, err := tokenFromFile(tokFile)
    if err != nil {
        tok = getTokenFromWeb(config)
        saveToken(tokFile, tok)
    }

    return config, tok, nil
}

func tokenFromFile(file string) (*oauth2.Token, error) {
    f, err := os.Open(file)
    if err != nil {
        return nil, err
    }
    defer f.Close()
    tok := &oauth2.Token{}
    err = json.NewDecoder(f).Decode(tok)
    return tok, err
}

func getTokenFromWeb(config *oauth2.Config) *oauth2.Token {
    authURL := config.AuthCodeURL("state-token", oauth2.AccessTypeOffline)
    fmt.Printf("Go to the following link in your browser then type the authorization code: \n%v\n", authURL)

    var authCode string
    if _, err := fmt.Scan(&authCode); err != nil {
        log.Fatalf("Unable to read authorization code: %v", err)
    }

    tok, err := config.Exchange(context.TODO(), authCode)
    if err != nil {
        log.Fatalf("Unable to retrieve token from web: %v", err)
    }
    return tok
}

func saveToken(path string, token *oauth2.Token) {
    fmt.Printf("Saving credential file to: %s\n", path)
    f, err := os.Create(path)
    if err != nil {
        log.Fatalf("Unable to cache oauth token: %v", err)
    }
    defer f.Close()
    json.NewEncoder(f).Encode(token)
}

func getNextWheelPosition() (int, error) {
    config, tok, err := getCreds()
    if err != nil {
        return AVAILABLE, err
    }

    client := config.Client(context.Background(), tok)
    srv, err := calendar.NewService(context.Background(), option.WithHTTPClient(client))
    if err != nil {
        return AVAILABLE, fmt.Errorf("unable to retrieve Calendar client: %v", err)
    }

    now := time.Now().Format(time.RFC3339)
    events, err := srv.Events.List("primary").ShowDeleted(false).
        SingleEvents(true).TimeMin(now).MaxResults(1).OrderBy("startTime").
        Do()
    if err != nil {
        return AVAILABLE, fmt.Errorf("unable to retrieve next events: %v", err)
    }

    if len(events.Items) == 0 {
        fmt.Println("No upcoming events found.")
        return AVAILABLE, nil
    }

    event := events.Items[0]
    eventType := event.EventType
    fmt.Printf("Next event type: %s\n", eventType)
    start := event.Start.DateTime
    if start == "" {
        start = event.Start.Date
    }

    startTime, _ := time.Parse(time.RFC3339, start)
    if eventType == "workingLocation" {
        if event.Summary != "Office" {
            return WORK_FROM_HOME, nil
        }
    } else if startTime.After(time.Now().Add(5 * time.Minute)) {
        fmt.Println("Next event is > 5 min from now, so AVAILABLE")
        return AVAILABLE, nil
    } else if startTime.After(time.Now()) {
        fmt.Println("Next event is <= 5 min from now, so GOING_TO_EVENT")
        return GOING_TO_EVENT, nil
    }

    if pos, ok := eventTypeToWheelPosition[eventType]; ok {
        return pos, nil
    }

    return AVAILABLE, nil
}

func connect(apiKeyID, apiKey, robotAddress string) (*client.RobotClient, error) {
	logger := logging.NewDebugLogger("client")
	machine, err := client.New(
		context.Background(),
		robotAddress,
		logger,
		client.WithDialOptions(rpc.WithEntityCredentials( 
			apiKeyID,
			rpc.Credentials{
				Type:    rpc.CredentialsTypeAPIKey, 
				Payload: apiKey,
			})),
	)
	if err != nil {
		logger.Fatal(err)
		return nil, err
	}
	
	return machine, nil
}

func controlWheel(wheelMotor viam.Motor, currentWheelPosition int) (int, error) {
    nextWheelPosition, err := getNextWheelPosition()
    if err != nil {
        return currentWheelPosition, err
    }

    if currentWheelPosition != nextWheelPosition {
        fmt.Printf("Turning wheel from %d to position %d\n", currentWheelPosition, nextWheelPosition)
        slices := currentWheelPosition - nextWheelPosition
        direction := int(math.Copysign(1, float64(slices)))
        for i := 0; i < int(math.Abs(float64(slices))); i++ {
            if err := wheelMotor.SetPower(context.Background(), -float64(direction)/6, nil); err != nil {
                fmt.Println("Exception happened", err)
                return currentWheelPosition, err
            }
            currentWheelPosition -= direction
        }
    }

    return currentWheelPosition, nil
}

func main() {
    apiKeyID := pflag.String("api-key-id", "", "The key id of the api key")
	apiKey := pflag.String("api-key", "", "The api key")
    robotAddress := pflag.String("robot-address", "", "Address of the robot")
    pflag.Parse()

    if *apiKeyID == "" || *apiKey == "" || *robotAddress == "" {
        log.Fatal("api-key-id, api-key, and robot-address are required flags")
    }

    fmt.Println("Connecting to robot")
    robot, err := connect(*apiKeyID, *apiKey, *robotAddress)
    if err != nil {
        log.Fatalf("Failed to connect to robot: %v", err)
    }

    fmt.Println("Turning wheel to initial position 0")
	wheelMotor, err := motor.FromRobot(robot, "wheel_motor")
	if err != nil {
		log.Printf("Failed to find motor: %v", err)
		return
	}

	for i := 0; i < 6; i++ {
		_ = wheelMotor.SetPower(context.Background(), -1.0/6, nil)
	}

    currentWheelPosition := 0
    for {
        currentWheelPosition, err = controlWheel(wheelMotor, currentWheelPosition)
        if err != nil {
            log.Printf("Exception happened during turning, trying to recover: %v", err)
        } else {
            time.Sleep(1 * time.Minute)
        }
    }
}
